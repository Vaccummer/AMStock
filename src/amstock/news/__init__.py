"""Pluggable news pipeline — collectors, processors, and orchestration."""

from __future__ import annotations

from amstock.news.collectors import (
    Collector,
    collect_source,
    get_collector,
    register_collector,
    registered_types,
)

try:
    from amstock.news.processors import (  # noqa: F811
        NewsProcessor,
        PassthroughProcessor,
        RatingProcessor,
        build_processor,
        register_processor,
    )
except ImportError:
    pass

try:
    from amstock.news.pipeline import NewsPipeline, build_pipeline  # noqa: F811
except ImportError:
    pass

__all__ = [
    "Collector",
    "NewsPipeline",
    "NewsProcessor",
    "PassthroughProcessor",
    "RatingProcessor",
    "build_pipeline",
    "build_processor",
    "collect_source",
    "get_collector",
    "register_collector",
    "register_processor",
    "registered_types",
]
