"""Pipeline engine — orchestrates collection, processing, and scheduling."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from amstock import news_server as _ns

if TYPE_CHECKING:
    from amstock.news_server import NewsServerConfig, NewsSourceConfig

from amstock.news.processors import NewsProcessor, build_processor


# ---------------------------------------------------------------------------
# NewsPipeline
# ---------------------------------------------------------------------------


@dataclass
class NewsPipeline:
    """Orchestrates per-source collection and processing."""

    config: NewsServerConfig
    _processors: dict[str, NewsProcessor]  # source_name -> processor

    def run_once(self) -> dict[str, object]:
        """Run one collection and rating cycle with per-source processors."""
        cfg = self.config
        _ns.ensure_news_schema(cfg.database_path)
        stats: dict[str, object] = {
            "sources": 0,
            "fetched": 0,
            "new": 0,
            "rated": 0,
            "errors": [],
        }
        now_epoch = int(time.time())
        all_errors = cast("list[dict[str, object]]", stats["errors"])

        for source in cfg.sources:
            if not source.enabled:
                continue
            if not _ns.source_due(cfg.database_path, source, now_epoch):
                continue
            token_index = _ns.source_token_index(cfg.database_path, source.name)
            if not _ns.source_active_at(source, cfg.timezone, now_epoch):
                _ns.defer_source_until_next_active(
                    cfg.database_path,
                    cfg,
                    source,
                    now_epoch,
                    token_index,
                )
                continue

            stats["sources"] = int(stats["sources"]) + 1

            # --- Collect ---
            try:
                items = _ns.collect_source(source, cfg, token_index)
            except Exception as exc:
                all_errors.append(
                    {
                        "source": source.name,
                        "error": {"type": type(exc).__name__, "message": str(exc)},
                    }
                )
                _ns.schedule_next_source_run(
                    cfg.database_path,
                    cfg,
                    source,
                    now_epoch,
                    _ns.source_next_token_index(source.name, token_index + 1),
                    f"{type(exc).__name__}: {exc}",
                )
                continue

            _ns.schedule_next_source_run(
                cfg.database_path,
                cfg,
                source,
                now_epoch,
                _ns.source_next_token_index(source.name, token_index + 1),
            )

            stats["fetched"] = int(stats["fetched"]) + len(items)

            # --- Store new items and group by this source ---
            source_items: list[tuple[int, dict[str, object]]] = []
            for item in items:
                item_id = _ns.insert_news_item(cfg.database_path, item)
                if item_id is None:
                    continue
                stats["new"] = int(stats["new"]) + 1
                source_items.append((item_id, item))

            # --- Process with source-specific processor ---
            if source_items:
                processor = self._processors.get(source.name)
                if processor is not None:
                    result = processor.process(
                        source_items,
                        source,
                        cfg.database_path,
                        cfg.ai,
                    )
                    stats["rated"] = int(stats["rated"]) + int(
                        result.get("rated", 0)
                    )
                    for err in result.get("errors", []):
                        all_errors.append(
                            {"source": source.name, "error": err.get("error", {})}
                        )

        return {
            "ok": True,
            "function": "news-once",
            **cast("dict[str, object]", stats),
        }

    def run_server(self, max_cycles: int | None = None) -> None:
        """Run the polling server loop with per-source processors."""
        cfg = self.config
        cycles = 0
        _ns.write_news_server_log(
            cfg,
            _ns.news_server_start_log_payload(cfg),
        )
        while True:
            cycle_started_at = int(time.time())
            try:
                payload = self.run_once()
            except Exception as exc:
                _ns.write_news_server_log(
                    cfg,
                    _ns.news_server_error_log_payload(
                        cfg, cycles + 1, cycle_started_at, exc
                    ),
                )
                raise
            cycles += 1
            _ns.write_news_server_log(
                cfg,
                _ns.news_server_cycle_log_payload(
                    cfg, cycles, cycle_started_at, payload, max_cycles
                ),
            )
            if max_cycles is not None and cycles >= max_cycles:
                return
            time.sleep(cfg.interval_seconds)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_pipeline(config: NewsServerConfig) -> NewsPipeline:
    """Build a ``NewsPipeline`` wired with per-source processors.

    Iterates over all configured sources and creates a processor for each
    based on ``source.processor_type``.
    """
    processors: dict[str, NewsProcessor] = {}
    for source in config.sources:
        processors[source.name] = build_processor(
            source.processor_type,
            config.ai,
            source.user_prompt,
        )
    return NewsPipeline(config=config, _processors=processors)
