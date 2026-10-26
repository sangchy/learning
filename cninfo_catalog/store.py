"""公告目录 SQLite。按 announcement_id 去重。"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from cninfo_catalog.parse import SHANGHAI

_SCHEMA = """
CREATE TABLE IF NOT EXISTS announcements (
    stock_code TEXT NOT NULL,
    short_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    announcement_date TEXT NOT NULL,
    category_name TEXT NOT NULL DEFAULT '',
    category_code TEXT NOT NULL DEFAULT '',
    announcement_id TEXT NOT NULL UNIQUE,
    adjunct_url TEXT,
    fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_announcements_code_date
    ON announcements (stock_code, announcement_date);

CREATE TABLE IF NOT EXISTS sync_watermarks (
    stock_code TEXT PRIMARY KEY,
    last_end_date TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class CatalogStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "CatalogStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def upsert_announcements(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        sql = """
        INSERT INTO announcements (
            stock_code, short_name, title, announcement_date,
            category_name, category_code, announcement_id, adjunct_url, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(announcement_id) DO UPDATE SET
            stock_code = excluded.stock_code,
            short_name = excluded.short_name,
            title = excluded.title,
            announcement_date = excluded.announcement_date,
            category_name = excluded.category_name,
            category_code = excluded.category_code,
            adjunct_url = excluded.adjunct_url,
            fetched_at = excluded.fetched_at
        """
        values = [
            (
                row["stock_code"],
                row["short_name"],
                row["title"],
                row["announcement_date"],
                row["category_name"],
                row["category_code"],
                row["announcement_id"],
                row["adjunct_url"],
                row["fetched_at"],
            )
            for row in rows
        ]
        with self._conn:
            self._conn.executemany(sql, values)
        return len(rows)

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM announcements").fetchone()
        return int(row["n"])

    def get_watermark(self, code: str) -> date | None:
        row = self._conn.execute(
            "SELECT last_end_date FROM sync_watermarks WHERE stock_code = ?",
            (code,),
        ).fetchone()
        if row is None:
            return None
        return date.fromisoformat(row["last_end_date"])

    def advance_watermark(self, code: str, end: date, updated_at: str | None = None) -> None:
        current = self.get_watermark(code)
        if current is not None and end <= current:
            return
        stamp = updated_at or datetime.now(SHANGHAI).isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute(
                """
                INSERT INTO sync_watermarks (stock_code, last_end_date, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(stock_code) DO UPDATE SET
                    last_end_date = excluded.last_end_date,
                    updated_at = excluded.updated_at
                """,
                (code, end.isoformat(), stamp),
            )

    def list_announcements(
        self,
        code: str,
        *,
        category_code: str | None = None,
        category_names: list[str] | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict]:
        clauses = ["stock_code = ?"]
        params: list[object] = [code]
        if start:
            clauses.append("announcement_date >= ?")
            params.append(start)
        if end:
            clauses.append("announcement_date <= ?")
            params.append(end)
        if category_code or category_names:
            match = []
            if category_code:
                match.append("category_code = ?")
                params.append(category_code)
            for name in category_names or []:
                match.append("category_name = ?")
                params.append(name)
            clauses.append("(" + " OR ".join(match) + ")")
        sql = (
            "SELECT stock_code, short_name, title, announcement_date, "
            "category_name, category_code, announcement_id, adjunct_url, fetched_at "
            "FROM announcements WHERE "
            + " AND ".join(clauses)
            + " ORDER BY announcement_date, announcement_id"
        )
        return [dict(row) for row in self._conn.execute(sql, params)]
