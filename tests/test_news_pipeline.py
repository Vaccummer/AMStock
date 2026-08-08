"""Tests for the pluggable news pipeline — collectors, processors, and pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from amstock import news_server
from amstock.news import collectors as news_collectors
from amstock.news.pipeline import NewsPipeline, build_pipeline
from amstock.news.processors import (
    NewsProcessor,
    PassthroughProcessor,
    RatingProcessor,
    build_processor,
    register_processor,
)
from amstock.news_server import (
    AIConfig,
    NewsServerConfig,
    NewsSourceConfig,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_ai_config(**overrides: object) -> AIConfig:
    kwargs: dict[str, object] = {
        "base_url": "https://api.test.example/v1",
        "api_key": "test-key-123",
        "model": "test-model",
        "timeout": 30.0,
        "sys_prompt": "你是金融新闻分类器。",
    }
    kwargs.update(overrides)
    return AIConfig(**kwargs)  # type: ignore[arg-type]


def _sample_source(
    name: str = "test-source",
    source_type: str = "akshare_flash",
    processor_type: str = "ai",
    user_prompt: str = "",
    **params: object,
) -> NewsSourceConfig:
    return NewsSourceConfig(
        name=name,
        type=source_type,
        enabled=True,
        interval_seconds=60,
        schedule_times=(),
        active_windows=(),
        limit=5,
        params=params,
        user_prompt=user_prompt,
        processor_type=processor_type,
    )


def _sample_config(
    tmp_path: Path,
    sources: list[NewsSourceConfig] | None = None,
) -> NewsServerConfig:
    db = tmp_path / "test.sqlite3"
    log = tmp_path / "test.log"
    if sources is None:
        sources = [_sample_source()]
    return NewsServerConfig(
        interval_seconds=60,
        database_path=db,
        log_path=log,
        timezone="Asia/Shanghai",
        ai=_sample_ai_config(),
        sources=tuple(sources),
    )


# ---------------------------------------------------------------------------
# Collector registry
# ---------------------------------------------------------------------------


class TestCollectorRegistry:
    def test_register_and_get(self) -> None:
        """Custom collectors can be registered and retrieved."""
        def my_collector(
            source: NewsSourceConfig,
            config: NewsServerConfig | None = None,
            token_index: int = 0,
        ) -> list[dict[str, object]]:
            return [{"title": "test"}]

        news_collectors.register_collector("custom-type", my_collector)
        assert news_collectors.get_collector("custom-type") is my_collector

    def test_unknown_type_raises(self) -> None:
        """Looking up an unregistered type raises ValueError."""
        with pytest.raises(ValueError, match="unsupported news source type"):
            news_collectors.get_collector("nonexistent-type")

    def test_builtin_types_registered(self) -> None:
        """All six built-in collector types are registered on import."""
        types = news_collectors.registered_types()
        assert "gdelt" in types
        assert "marketaux" in types
        assert "akshare_flash" in types
        assert "akshare_economic_calendar" in types
        assert "akshare_stock" in types
        assert "akshare_notice" in types

    def test_collect_source_dispatches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """collect_source calls the registered collector for the source type."""
        calls: list[dict[str, object]] = []

        def fake_collector(
            source: NewsSourceConfig,
            config: NewsServerConfig | None = None,
            token_index: int = 0,
        ) -> list[dict[str, object]]:
            calls.append({"name": source.name, "token_index": token_index})
            return []

        monkeypatch.setitem(news_collectors._COLLECTORS, "test-dispatch", fake_collector)
        source = _sample_source(name="dispatched", source_type="test-dispatch")
        result = news_collectors.collect_source(source, token_index=42)
        assert result == []
        assert len(calls) == 1
        assert calls[0]["name"] == "dispatched"
        assert calls[0]["token_index"] == 42


# ---------------------------------------------------------------------------
# RatingProcessor
# ---------------------------------------------------------------------------


class TestRatingProcessor:
    def test_prompt_merging_with_source_prompt(self) -> None:
        """Source user_prompt is appended to the global sys_prompt."""
        ai = _sample_ai_config(sys_prompt="全局提示词。")
        processor = RatingProcessor(ai, "重点关注A股。")
        merged = processor._ai_config.sys_prompt
        assert "全局提示词。" in merged
        assert "重点关注A股。" in merged
        assert merged.index("全局提示词。") < merged.index("重点关注A股。")

    def test_prompt_merging_without_source_prompt(self) -> None:
        """Empty user_prompt yields unchanged global prompt."""
        ai = _sample_ai_config(sys_prompt="全局提示词。")
        processor = RatingProcessor(ai, "")
        assert processor._ai_config.sys_prompt == "全局提示词。"

    def test_process_calls_ai_and_stores_reviews(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RatingProcessor calls the AI and stores review records."""
        db = tmp_path / "test.sqlite3"
        news_server.ensure_news_schema(db)

        # Insert a news item first
        item_id = news_server.insert_news_item(
            db,
            {
                "source": "test",
                "provider": "test",
                "title": "测试新闻",
                "summary": "摘要",
                "url": "https://example.test",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": "test-fp-001",
                "raw_json": "{}",
            },
        )
        assert item_id is not None

        # Mock AI response
        ai_response = json.dumps(
            {
                "items": [
                    {
                        "news_id": item_id,
                        "keep": True,
                        "category": "宏观经济",
                        "importance": 4,
                        "urgency": 3,
                        "event": "重要经济数据发布",
                        "reason": "影响市场预期",
                    }
                ]
            }
        )
        monkeypatch.setattr(
            news_server,
            "openai_chat_completion",
            lambda _config, _messages: ai_response,
        )

        ai = _sample_ai_config()
        source = _sample_source()
        processor = RatingProcessor(ai, "重点关注宏观。")

        result = processor.process(
            [(item_id, {"title": "测试新闻"})],
            source,
            db,
            ai,
        )
        assert result["rated"] == 1

        # Verify review was written
        reviews = news_server.list_news_items(db, limit=1, category="宏观经济")
        assert len(reviews) == 1
        assert int(reviews[0]["review_importance"]) == 4
        assert reviews[0]["review_category"] == "宏观经济"

    def test_process_handles_ai_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falling-back when the AI call fails still stores a review."""
        db = tmp_path / "test.sqlite3"
        news_server.ensure_news_schema(db)

        item_id = news_server.insert_news_item(
            db,
            {
                "source": "test",
                "provider": "test",
                "title": "故障新闻",
                "summary": "摘要",
                "url": "https://example.test",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": "test-fp-fail",
                "raw_json": "{}",
            },
        )
        assert item_id is not None

        monkeypatch.setattr(
            news_server,
            "openai_chat_completion",
            lambda _config, _messages: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        ai = _sample_ai_config()
        source = _sample_source()
        processor = RatingProcessor(ai)
        result = processor.process(
            [(item_id, {"title": "故障新闻"})],
            source,
            db,
            ai,
        )
        assert result["rated"] == 1
        reviews = news_server.list_news_items(db, limit=1)
        assert len(reviews) == 1
        assert reviews[0]["review_importance"] == 1  # fallback importance
        assert reviews[0]["review_push"] == 0  # fallback keep=False


# ---------------------------------------------------------------------------
# PassthroughProcessor
# ---------------------------------------------------------------------------


class TestPassthroughProcessor:
    def test_process_stores_passthrough_reviews(self, tmp_path: Path) -> None:
        """Items are stored with default non-keep passthrough reviews."""
        db = tmp_path / "test.sqlite3"
        news_server.ensure_news_schema(db)

        item_id = news_server.insert_news_item(
            db,
            {
                "source": "test",
                "provider": "test",
                "title": "归档新闻",
                "summary": "内容",
                "url": "https://example.test",
                "published_at": "2026-07-15T10:00:00",
                "fingerprint": "test-fp-pt",
                "raw_json": "{}",
            },
        )
        assert item_id is not None

        source = _sample_source()
        processor = PassthroughProcessor()
        result = processor.process(
            [(item_id, {"title": "归档新闻"})],
            source,
            db,
            _sample_ai_config(),
        )
        assert result["rated"] == 1

        reviews = news_server.list_news_items(db, limit=1)
        assert len(reviews) == 1
        assert reviews[0]["review_push"] == 0
        assert int(reviews[0]["review_importance"]) == 1


# ---------------------------------------------------------------------------
# Processor registry / build_processor
# ---------------------------------------------------------------------------


class TestProcessorRegistry:
    def test_build_processor_ai(self) -> None:
        """build_processor("ai") returns a RatingProcessor."""
        ai = _sample_ai_config()
        proc = build_processor("ai", ai, "source prompt")
        assert isinstance(proc, RatingProcessor)
        assert "source prompt" in proc._ai_config.sys_prompt

    def test_build_processor_passthrough(self) -> None:
        """build_processor("passthrough") returns a PassthroughProcessor."""
        proc = build_processor("passthrough", _sample_ai_config())
        assert isinstance(proc, PassthroughProcessor)

    def test_build_processor_unknown_raises(self) -> None:
        """Unknown processor type raises ValueError."""
        with pytest.raises(ValueError, match="unknown processor type"):
            build_processor("ghost-processor", _sample_ai_config())

    def test_register_custom_processor(self, tmp_path: Path) -> None:
        """Custom processor classes can be registered and built."""

        class CustomProc(NewsProcessor):
            def process(self, items, source, database_path, ai):
                return {"rated": len(items), "errors": []}

        register_processor("custom", CustomProc)
        try:
            proc = build_processor("custom", _sample_ai_config())
            assert isinstance(proc, CustomProc)
        finally:
            # Clean up so other tests aren't affected
            from amstock.news.processors import _PROCESSOR_CLASSES

            _PROCESSOR_CLASSES.pop("custom", None)


# ---------------------------------------------------------------------------
# NewsPipeline
# ---------------------------------------------------------------------------


class TestNewsPipeline:
    def test_run_once_single_source_with_rating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pipeline runs one source and returns correct stats."""
        db = tmp_path / "test.sqlite3"
        news_server.ensure_news_schema(db)

        # Mock collection to return one item
        monkeypatch.setitem(
            news_collectors._COLLECTORS,
            "akshare_flash",
            lambda s, c, ti: [
                {
                    "source": s.name,
                    "provider": "test",
                    "title": "测试",
                    "summary": "",
                    "url": "",
                    "published_at": "",
                    "fingerprint": "fp-pipeline-1",
                    "raw_json": "{}",
                }
            ],
        )

        # Mock AI response
        monkeypatch.setattr(
            news_server,
            "openai_chat_completion",
            lambda _c, _m: json.dumps(
                {"items": [{"news_id": 1, "keep": True, "category": "A股市场", "importance": 3, "urgency": 2, "event": "test"}]}
            ),
        )

        config = _sample_config(tmp_path)
        pipeline = build_pipeline(config)
        result = pipeline.run_once()

        assert result["ok"] is True
        assert result["sources"] == 1
        assert result["fetched"] == 1
        assert result["new"] == 1
        assert result["rated"] == 1

    def test_run_once_multi_source_different_processors(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two sources — one 'ai', one 'passthrough' — each get their processor."""
        db = tmp_path / "test.sqlite3"
        news_server.ensure_news_schema(db)

        ai_calls: list[str] = []
        finger = [0]

        def fake_ai(_c: object, _m: object) -> str:
            ai_calls.append("called")
            finger[0] += 1
            return json.dumps(
                {"items": [{"news_id": finger[0], "keep": True, "category": "其他", "importance": 2, "urgency": 1, "event": "x"}]}
            )

        monkeypatch.setattr(news_server, "openai_chat_completion", fake_ai)

        # One source uses akshare_flash with "ai" processor,
        # the other akshare_flash with "passthrough"
        monkeypatch.setitem(
            news_collectors._COLLECTORS,
            "akshare_flash",
            lambda s, c, ti: [
                {
                    "source": s.name,
                    "provider": "test",
                    "title": s.name,
                    "summary": "",
                    "url": "",
                    "published_at": "",
                    "fingerprint": f"fp-{s.name}",
                    "raw_json": "{}",
                }
            ],
        )

        sources = [
            _sample_source(name="rated-src", processor_type="ai"),
            _sample_source(name="pass-src", processor_type="passthrough"),
        ]
        config = _sample_config(tmp_path, sources=sources)
        pipeline = build_pipeline(config)
        result = pipeline.run_once()

        assert result["sources"] == 2
        assert result["new"] == 2
        assert result["rated"] == 2  # both store reviews, but only one via AI
        assert len(ai_calls) == 1  # only the 'ai' source triggered AI

    def test_run_once_skips_non_due_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Sources that are not yet due are skipped."""
        db = tmp_path / "test.sqlite3"
        news_server.ensure_news_schema(db)

        source = _sample_source(name="future-src")
        config = _sample_config(tmp_path, sources=[source])

        # Set next_run_at far in the future
        news_server.schedule_next_source_run(
            db,
            config,
            source,
            int(__import__("time").time()) + 999999,
            0,
        )

        monkeypatch.setitem(
            news_collectors._COLLECTORS,
            "akshare_flash",
            lambda s, c, ti: [{"source": s.name, "provider": "t", "title": "x", "summary": "", "url": "", "published_at": "", "fingerprint": "fp-future", "raw_json": "{}"}],
        )
        monkeypatch.setattr(
            news_server,
            "openai_chat_completion",
            lambda _c, _m: json.dumps({"items": []}),
        )

        pipeline = build_pipeline(config)
        result = pipeline.run_once()

        assert result["sources"] == 0
        assert result["fetched"] == 0

    def test_build_pipeline_default_processor_type(self, tmp_path: Path) -> None:
        """Missing processor_type defaults to 'ai' (RatingProcessor)."""
        config = _sample_config(tmp_path)
        pipeline = build_pipeline(config)
        proc = pipeline._processors.get("test-source")
        assert isinstance(proc, RatingProcessor)

    def test_build_pipeline_respects_processor_type(self, tmp_path: Path) -> None:
        """processor_type="passthrough" creates a PassthroughProcessor."""
        sources = [_sample_source(name="pass-src", processor_type="passthrough")]
        config = _sample_config(tmp_path, sources=sources)
        pipeline = build_pipeline(config)
        proc = pipeline._processors.get("pass-src")
        assert isinstance(proc, PassthroughProcessor)
