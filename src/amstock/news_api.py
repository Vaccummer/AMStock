"""FastAPI application for news query API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from amstock.news_server import (
    NewsServerConfig,
    count_news_items,
    ensure_news_schema,
    list_news_items,
    load_news_server_config,
    news_list_row_payload,
    source_schedule_snapshots,
)


def create_app(config: NewsServerConfig | None = None) -> FastAPI:
    """Create the FastAPI application."""

    cfg = config or load_news_server_config()
    app = FastAPI(
        title="AMStock News API",
        description="Query rated and classified financial news",
        version="0.1.0",
    )

    @app.get("/api/v1/news")
    def list_news(
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
        source: Annotated[str, Query()] = "",
        provider: Annotated[str, Query()] = "",
        query: Annotated[str, Query(description="Keyword search in title and summary")] = "",
        since: Annotated[str, Query(description="ISO datetime lower bound")] = "",
        until: Annotated[str, Query(description="ISO datetime upper bound")] = "",
        category: Annotated[str, Query(description="Exact category match")] = "",
        min_importance: Annotated[int, Query(ge=1, le=5)] = 1,
        max_importance: Annotated[int, Query(ge=1, le=5)] = 5,
        min_urgency: Annotated[int, Query(ge=1, le=5)] = 1,
        max_urgency: Annotated[int, Query(ge=1, le=5)] = 5,
        keep: Annotated[bool | None, Query()] = None,
        event: Annotated[str, Query(description="Search in event summary")] = "",
        sort_by: Annotated[
            str, Query(description="Sort field: published_at, importance, urgency, first_seen_at")
        ] = "first_seen_at",
        sort_order: Annotated[str, Query(description="Sort direction: asc or desc")] = "desc",
    ) -> dict[str, object]:
        """List news items with filters, sorting, and pagination."""

        ensure_news_schema(cfg.database_path)
        total = count_news_items(
            cfg.database_path,
            source=source,
            provider=provider,
            query=query,
            since=since,
            until=until,
            category=category,
            min_importance=min_importance,
            max_importance=max_importance,
            keep=keep,
        )
        rows = list_news_items(
            cfg.database_path,
            limit=limit,
            offset=offset,
            source=source,
            provider=provider,
            query=query,
            since=since,
            until=until,
            category=category,
            min_importance=min_importance,
            max_importance=max_importance,
            min_urgency=min_urgency,
            max_urgency=max_urgency,
            keep=keep,
            event=event,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        items = [news_list_row_payload(row) for row in rows]
        return {
            "ok": True,
            "total": total,
            "limit": limit,
            "offset": offset,
            "returned_rows": len(items),
            "items": items,
        }

    @app.get("/api/v1/news/{item_id}")
    def get_news_item(item_id: int) -> dict[str, object]:
        """Get a single news item with all rating history."""

        ensure_news_schema(cfg.database_path)
        rows = list_news_items(
            cfg.database_path,
            limit=1,
            offset=item_id - 1,
            sort_by="id",
            sort_order="asc",
        )
        if not rows:
            raise HTTPException(status_code=404, detail="News item not found")
        row = rows[0]
        if int(row["id"]) != item_id:
            # Try direct lookup
            import sqlite3

            with sqlite3.connect(cfg.database_path) as conn:
                conn.row_factory = sqlite3.Row
                item_row = conn.execute(
                    "SELECT * FROM news_items WHERE id = ?", (item_id,)
                ).fetchone()
                if not item_row:
                    raise HTTPException(status_code=404, detail="News item not found")
                reviews = conn.execute(
                    """SELECT * FROM news_reviews
                       WHERE news_item_id = ? ORDER BY id DESC""",
                    (item_id,),
                ).fetchall()
        else:
            import sqlite3

            with sqlite3.connect(cfg.database_path) as conn:
                conn.row_factory = sqlite3.Row
                item_row = conn.execute(
                    "SELECT * FROM news_items WHERE id = ?", (item_id,)
                ).fetchone()
                reviews = conn.execute(
                    """SELECT * FROM news_reviews
                       WHERE news_item_id = ? ORDER BY id DESC""",
                    (item_id,),
                ).fetchall()

        item_data = dict(item_row) if item_row else {}
        item_data["rating"] = news_list_row_payload(row).get("rating")
        item_data["reviews"] = [dict(r) for r in reviews] if reviews else []
        return {"ok": True, "item": item_data}

    @app.get("/api/v1/news/stats")
    def get_stats(
        since: Annotated[str, Query(description="ISO datetime for recent filter")] = "",
    ) -> dict[str, object]:
        """Get aggregate news statistics."""

        import sqlite3

        ensure_news_schema(cfg.database_path)
        now = datetime.now(timezone.utc)
        today_iso = now.strftime("%Y-%m-%dT00:00:00")
        week_iso = (now - timedelta(days=7)).isoformat()

        with sqlite3.connect(cfg.database_path) as conn:
            conn.row_factory = sqlite3.Row

            total = conn.execute("SELECT COUNT(*) FROM news_items").fetchone()[0]
            today_count = conn.execute(
                "SELECT COUNT(*) FROM news_items WHERE first_seen_at >= ?",
                (today_iso,),
            ).fetchone()[0]
            week_count = conn.execute(
                "SELECT COUNT(*) FROM news_items WHERE first_seen_at >= ?",
                (week_iso,),
            ).fetchone()[0]

            by_category_rows = conn.execute(
                """SELECT r.category, COUNT(DISTINCT r.news_item_id) AS cnt
                   FROM news_reviews r
                   WHERE r.category != ''
                   GROUP BY r.category ORDER BY cnt DESC"""
            ).fetchall()
            by_category = {str(r["category"]): int(r["cnt"]) for r in by_category_rows}

            by_importance_rows = conn.execute(
                """SELECT r.importance, COUNT(*) AS cnt
                   FROM news_reviews r
                   WHERE r.importance > 0
                   GROUP BY r.importance ORDER BY r.importance"""
            ).fetchall()
            by_importance = {str(r["importance"]): int(r["cnt"]) for r in by_importance_rows}

            by_urgency_rows = conn.execute(
                """SELECT r.urgent, COUNT(*) AS cnt
                   FROM news_reviews r
                   GROUP BY r.urgent"""
            ).fetchall()
            by_urgency = {
                "high": sum(int(r["cnt"]) for r in by_urgency_rows if r["urgent"]),
                "normal": sum(int(r["cnt"]) for r in by_urgency_rows if not r["urgent"]),
            }

            by_source_rows = conn.execute(
                "SELECT source, COUNT(*) AS cnt FROM news_items GROUP BY source ORDER BY cnt DESC"
            ).fetchall()
            by_source = {str(r["source"]): int(r["cnt"]) for r in by_source_rows}

            by_provider_rows = conn.execute(
                "SELECT provider, COUNT(*) AS cnt FROM news_items GROUP BY provider ORDER BY cnt DESC"
            ).fetchall()
            by_provider = {str(r["provider"]): int(r["cnt"]) for r in by_provider_rows}

        return {
            "ok": True,
            "total_items": total,
            "today_count": today_count,
            "week_count": week_count,
            "by_category": by_category,
            "by_importance": by_importance,
            "by_urgency": by_urgency,
            "by_source": by_source,
            "by_provider": by_provider,
        }

    @app.get("/api/v1/news/categories")
    def get_categories() -> dict[str, object]:
        """Get distinct categories from rated news."""

        import sqlite3

        ensure_news_schema(cfg.database_path)
        with sqlite3.connect(cfg.database_path) as conn:
            rows = conn.execute(
                """SELECT DISTINCT r.category FROM news_reviews r
                   WHERE r.category != '' ORDER BY r.category"""
            ).fetchall()
        categories = [str(r[0]) for r in rows]
        return {"ok": True, "categories": categories}

    @app.get("/api/v1/news/sources")
    def get_sources() -> dict[str, object]:
        """Get source status."""

        now_epoch = int(__import__("time").time())
        sources = source_schedule_snapshots(cfg, now_epoch)
        return {"ok": True, "sources": sources}

    return app
