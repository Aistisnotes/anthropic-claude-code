"""SQLite-backed storage for pipeline state and results."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from meta_ads_analyzer.models import (
    AdAnalysis,
    AdContent,
    AdStatus,
    AdType,
    FilterReason,
    ScrapedAd,
)

DB_PATH = Path("output/meta_ads.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    search_query TEXT NOT NULL,
    brand TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT DEFAULT 'running',
    config_json TEXT
);

CREATE TABLE IF NOT EXISTS scraped_ads (
    ad_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    page_name TEXT,
    page_id TEXT,
    ad_type TEXT,
    primary_text TEXT,
    headline TEXT,
    description TEXT,
    cta_text TEXT,
    link_url TEXT,
    media_url TEXT,
    thumbnail_url TEXT,
    started_running TEXT,
    platforms_json TEXT,
    scrape_position INTEGER DEFAULT 0,
    scraped_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS ad_content (
    ad_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    brand TEXT,
    ad_type TEXT,
    primary_text TEXT,
    headline TEXT,
    transcript TEXT,
    transcript_confidence REAL DEFAULT 0.0,
    media_path TEXT,
    word_count INTEGER DEFAULT 0,
    scrape_position INTEGER DEFAULT 0,
    status TEXT DEFAULT 'scraped',
    filter_reason TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS ad_analyses (
    ad_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    brand TEXT,
    analysis_json TEXT NOT NULL,
    analysis_confidence REAL DEFAULT 0.0,
    copy_quality_score REAL DEFAULT 0.0,
    created_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_scraped_ads_run ON scraped_ads(run_id);
CREATE INDEX IF NOT EXISTS idx_ad_content_run ON ad_content(run_id);
CREATE INDEX IF NOT EXISTS idx_ad_content_status ON ad_content(status);
CREATE INDEX IF NOT EXISTS idx_ad_analyses_run ON ad_analyses(run_id);
"""


class AdStore:
    """Async SQLite store for pipeline data."""

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self._db: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, *args):
        await self.close()

    # --- Runs ---

    async def create_run(
        self, run_id: str, search_query: str, brand: str | None, config: dict
    ) -> None:
        await self._db.execute(
            "INSERT INTO runs (run_id, search_query, brand, started_at, config_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, search_query, brand, datetime.utcnow().isoformat(), json.dumps(config)),
        )
        await self._db.commit()

    async def complete_run(self, run_id: str, status: str = "completed") -> None:
        await self._db.execute(
            "UPDATE runs SET completed_at = ?, status = ? WHERE run_id = ?",
            (datetime.utcnow().isoformat(), status, run_id),
        )
        await self._db.commit()

    # --- Scraped ads ---

    async def save_scraped_ad(self, run_id: str, ad: ScrapedAd) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO scraped_ads "
            "(ad_id, run_id, page_name, page_id, ad_type, primary_text, headline, "
            "description, cta_text, link_url, media_url, thumbnail_url, "
            "started_running, platforms_json, scrape_position, scraped_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ad.ad_id,
                run_id,
                ad.page_name,
                ad.page_id,
                ad.ad_type.value,
                ad.primary_text,
                ad.headline,
                ad.description,
                ad.cta_text,
                ad.link_url,
                ad.media_url,
                ad.thumbnail_url,
                ad.started_running,
                json.dumps(ad.platforms),
                ad.scrape_position,
                ad.scraped_at.isoformat(),
            ),
        )
        await self._db.commit()

    async def get_scraped_ads(self, run_id: str) -> list[ScrapedAd]:
        cursor = await self._db.execute(
            "SELECT * FROM scraped_ads WHERE run_id = ? ORDER BY scrape_position ASC",
            (run_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            results.append(
                ScrapedAd(
                    ad_id=row["ad_id"],
                    page_name=row["page_name"],
                    page_id=row["page_id"],
                    ad_type=AdType(row["ad_type"]) if row["ad_type"] else AdType.UNKNOWN,
                    primary_text=row["primary_text"],
                    headline=row["headline"],
                    description=row["description"],
                    cta_text=row["cta_text"],
                    link_url=row["link_url"],
                    media_url=row["media_url"],
                    thumbnail_url=row["thumbnail_url"],
                    started_running=row["started_running"],
                    platforms=json.loads(row["platforms_json"]) if row["platforms_json"] else [],
                    scrape_position=row["scrape_position"] if "scrape_position" in row.keys() else 0,
                )
            )
        return results

    # --- Ad content ---

    async def save_ad_content(self, run_id: str, content: AdContent) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO ad_content "
            "(ad_id, run_id, brand, ad_type, primary_text, headline, transcript, "
            "transcript_confidence, media_path, word_count, scrape_position, "
            "status, filter_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                content.ad_id,
                run_id,
                content.brand,
                content.ad_type.value,
                content.primary_text,
                content.headline,
                content.transcript,
                content.transcript_confidence,
                str(content.media_path) if content.media_path else None,
                content.word_count,
                content.scrape_position,
                content.status.value,
                content.filter_reason.value if content.filter_reason else None,
            ),
        )
        await self._db.commit()

    async def get_ad_contents(
        self, run_id: str, status: AdStatus | None = None
    ) -> list[AdContent]:
        if status:
            cursor = await self._db.execute(
                "SELECT * FROM ad_content WHERE run_id = ? AND status = ? "
                "ORDER BY scrape_position ASC",
                (run_id, status.value),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM ad_content WHERE run_id = ? ORDER BY scrape_position ASC",
                (run_id,),
            )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            results.append(
                AdContent(
                    ad_id=row["ad_id"],
                    brand=row["brand"] or "",
                    ad_type=AdType(row["ad_type"]) if row["ad_type"] else AdType.UNKNOWN,
                    primary_text=row["primary_text"],
                    headline=row["headline"],
                    transcript=row["transcript"],
                    transcript_confidence=row["transcript_confidence"] or 0.0,
                    media_path=Path(row["media_path"]) if row["media_path"] else None,
                    word_count=row["word_count"] or 0,
                    scrape_position=row["scrape_position"] if "scrape_position" in row.keys() else 0,
                    status=AdStatus(row["status"]),
                    filter_reason=(
                        FilterReason(row["filter_reason"]) if row["filter_reason"] else None
                    ),
                )
            )
        return results

    # --- Analyses ---

    async def save_analysis(self, run_id: str, analysis: AdAnalysis) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO ad_analyses "
            "(ad_id, run_id, brand, analysis_json, analysis_confidence, "
            "copy_quality_score, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                analysis.ad_id,
                run_id,
                analysis.brand,
                analysis.model_dump_json(),
                analysis.analysis_confidence,
                analysis.copy_quality_score,
                datetime.utcnow().isoformat(),
            ),
        )
        await self._db.commit()

    async def get_analyses(self, run_id: str) -> list[AdAnalysis]:
        cursor = await self._db.execute(
            "SELECT analysis_json FROM ad_analyses WHERE run_id = ?", (run_id,)
        )
        rows = await cursor.fetchall()
        return [AdAnalysis.model_validate_json(row["analysis_json"]) for row in rows]

    # --- Stats ---

    async def get_run_stats(self, run_id: str) -> dict:
        stats = {}
        for table in ("scraped_ads", "ad_content", "ad_analyses"):
            cursor = await self._db.execute(
                f"SELECT COUNT(*) as cnt FROM {table} WHERE run_id = ?", (run_id,)
            )
            row = await cursor.fetchone()
            stats[table] = row["cnt"]

        cursor = await self._db.execute(
            "SELECT status, COUNT(*) as cnt FROM ad_content WHERE run_id = ? GROUP BY status",
            (run_id,),
        )
        rows = await cursor.fetchall()
        stats["content_by_status"] = {row["status"]: row["cnt"] for row in rows}

        return stats
