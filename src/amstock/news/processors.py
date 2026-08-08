"""Processor protocol and implementations for per-source news handling."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from amstock.news_server import AIConfig, NewsSourceConfig

# ---------------------------------------------------------------------------
# Processor ABC
# ---------------------------------------------------------------------------


class NewsProcessor(ABC):
    """Pluggable processor for a source's post-collection pipeline.

    Each source can have its own processor instance, configured with
    source-specific prompts and behaviour.
    """

    @abstractmethod
    def process(
        self,
        items: list[tuple[int, dict[str, object]]],
        source: NewsSourceConfig,
        database_path: Path,
        ai: AIConfig,
    ) -> dict[str, object]:
        """Process new items (rate, filter, store) and return stats.

        Args:
            items: List of (item_id, item_dict) from insert_news_item.
            source: The source configuration.
            database_path: Path to the SQLite database.
            ai: AI provider configuration (may be used or ignored).

        Returns:
            Stats dict: ``{"rated": int, "errors": list[dict]}``.
        """
        ...


# ---------------------------------------------------------------------------
# PassthroughProcessor — no AI, just archive
# ---------------------------------------------------------------------------


class PassthroughProcessor(NewsProcessor):
    """Store items with default non-keep reviews — no AI calls."""

    def process(
        self,
        items: list[tuple[int, dict[str, object]]],
        source: NewsSourceConfig,
        database_path: Path,
        ai: AIConfig,
    ) -> dict[str, object]:
        """Store passthrough reviews for every item."""
        from amstock.news_server import rating_to_review, save_news_review

        stats: dict[str, object] = {"rated": 0, "errors": []}
        for item_id, item in items:
            rating: dict[str, object] = {
                "news_id": item_id,
                "keep": False,
                "category": "其他",
                "importance": 1,
                "urgency": 1,
                "event": str(item.get("title") or ""),
                "reason": "passthrough — no AI rating configured",
                "raw_response": json.dumps({"processor": "passthrough"}, ensure_ascii=False),
            }
            save_news_review(database_path, item_id, rating_to_review(rating))
            stats["rated"] = int(stats["rated"]) + 1
        return stats


# ---------------------------------------------------------------------------
# RatingProcessor — AI classification with source-specific prompt
# ---------------------------------------------------------------------------


class RatingProcessor(NewsProcessor):
    """Rate items via AI using a merged global + source-specific prompt."""

    def __init__(self, ai_config: AIConfig, source_user_prompt: str = "") -> None:
        """Create a rating processor with merged prompts.

        Args:
            ai_config: The global AI provider configuration.
            source_user_prompt: Per-source additional prompt instructions.
        """
        # Merge prompts once at construction time
        merged = ai_config.sys_prompt
        if source_user_prompt.strip():
            merged = merged.rstrip() + "\n\n" + source_user_prompt.strip()

        # Build a new AIConfig with the merged prompt (both are frozen dataclasses)
        from amstock.news_server import AIConfig as _AIConfig

        self._ai_config: AIConfig = _AIConfig(
            base_url=ai_config.base_url,
            api_key=ai_config.api_key,
            model=ai_config.model,
            timeout=ai_config.timeout,
            sys_prompt=merged,
        )

    def process(
        self,
        items: list[tuple[int, dict[str, object]]],
        source: NewsSourceConfig,
        database_path: Path,
        ai: AIConfig,
    ) -> dict[str, object]:
        """Rate items with source-specific AI prompt and store reviews."""
        from amstock.news_server import (
            chunk_items,
            fallback_rating,
            find_rating_for_item,
            normalize_rating,
            rate_news_items,
            rating_to_review,
            save_news_review,
        )

        stats: dict[str, object] = {"rated": 0, "errors": []}
        if not items:
            return stats

        for batch in chunk_items(items, 30):
            try:
                ratings = self._rate_batch(batch)
            except Exception as exc:
                cast("list[dict[str, object]]", stats["errors"]).append(
                    {"error": {"type": type(exc).__name__, "message": str(exc)}}
                )
                continue
            for item_id, item in batch:
                rating = normalize_rating(
                    find_rating_for_item(ratings, item_id),
                    item_id,
                    item,
                )
                rating["raw_response"] = json.dumps(
                    rating, ensure_ascii=False, sort_keys=True
                )
                save_news_review(database_path, item_id, rating_to_review(rating))
                stats["rated"] = int(stats["rated"]) + 1
        return stats

    def _rate_batch(
        self, items: list[tuple[int, dict[str, object]]]
    ) -> list[dict[str, object]]:
        """Call AI to rate one batch using our merged-prompt config."""
        from amstock.news_server import (
            build_rating_messages,
            fallback_rating,
            openai_chat_completion,
            parse_json_object,
        )

        if not self._ai_config.api_key:
            return [
                fallback_rating(item_id, item, "missing ai api_key")
                for item_id, item in items
            ]
        messages = build_rating_messages(self._ai_config.sys_prompt, items)
        try:
            response_text = openai_chat_completion(self._ai_config, messages)
        except Exception:
            return [
                fallback_rating(item_id, item, "ai request failed")
                for item_id, item in items
            ]
        parsed = parse_json_object(response_text)
        raw_items: list[dict[str, object]] = []
        if isinstance(parsed, dict):
            raw = parsed.get("items") or parsed.get("ratings") or parsed.get("data")
            raw_items = raw if isinstance(raw, list) else []
        ratings = [r for r in raw_items if isinstance(r, dict)]
        if not ratings:
            return [
                fallback_rating(item_id, item, response_text)
                for item_id, item in items
            ]
        return ratings


# ---------------------------------------------------------------------------
# Processor registry
# ---------------------------------------------------------------------------

_PROCESSOR_CLASSES: dict[str, type[NewsProcessor]] = {
    "ai": RatingProcessor,
    "passthrough": PassthroughProcessor,
}


def register_processor(name: str, processor_cls: type[NewsProcessor]) -> None:
    """Register a custom processor class for use in source configs."""
    _PROCESSOR_CLASSES[name] = processor_cls


def build_processor(
    processor_type: str,
    ai: AIConfig,
    user_prompt: str = "",
) -> NewsProcessor:
    """Create a processor instance by name.

    ``"ai"`` maps to ``RatingProcessor``, ``"passthrough"`` maps to
    ``PassthroughProcessor``.  Any other name is looked up in the registry.
    """
    cls = _PROCESSOR_CLASSES.get(processor_type)
    if cls is None:
        msg = f"unknown processor type {processor_type!r}"
        raise ValueError(msg)
    if cls is RatingProcessor:
        return cls(ai, user_prompt)
    return cls()
