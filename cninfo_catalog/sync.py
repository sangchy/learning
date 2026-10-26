"""按股票同步目录，并在整段成功后前移水位。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from cninfo_catalog.categories import join_categories
from cninfo_catalog.client import CninfoClient, CninfoError
from cninfo_catalog.parse import SHANGHAI, effective_window, parse_announcement
from cninfo_catalog.store import CatalogStore


@dataclass
class SyncResult:
    code: str
    short_name: str
    column: str
    org_id: str
    start: str
    end: str
    rows: int
    skipped: bool
    message: str


def run_sync(
    *,
    client: CninfoClient,
    store: CatalogStore,
    codes: list[str],
    categories: list[str],
    start: date | None,
    end: date | None,
    incremental: bool,
    today: date | None = None,
    now: datetime | None = None,
) -> list[SyncResult]:
    category_param = join_categories(categories)
    filter_codes = [part for part in category_param.split(";") if part]
    moment = now if now is not None else datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    fetched_at = moment.astimezone(SHANGHAI).isoformat(timespec="seconds")
    current_day = today or moment.astimezone(SHANGHAI).date()
    results: list[SyncResult] = []
    failures: list[str] = []

    for code in codes:
        watermark = store.get_watermark(code) if incremental else None
        try:
            window = effective_window(start, end, watermark, incremental, current_day)
        except ValueError as exc:
            failures.append(f"{code}: {exc}")
            continue
        if window is None:
            assert watermark is not None
            results.append(
                SyncResult(
                    code=code,
                    short_name="",
                    column="",
                    org_id="",
                    start="",
                    end=watermark.isoformat(),
                    rows=0,
                    skipped=True,
                    message=f"{code} 已同步到 {watermark.isoformat()}，本次没有新的日期",
                )
            )
            continue
        window_start, window_end = window
        try:
            company = client.lookup_company(code)
            raw_rows = client.fetch_announcements(
                code=company["code"],
                org_id=company["org_id"],
                column=company["column"],
                start=window_start.isoformat(),
                end=window_end.isoformat(),
                category=category_param,
            )
            parsed = [
                parse_announcement(
                    item,
                    stock_code=company["code"],
                    short_name=company["short_name"],
                    filter_codes=filter_codes,
                    fetched_at=fetched_at,
                )
                for item in raw_rows
            ]
            stored = store.upsert_announcements(parsed)
            store.advance_watermark(code, window_end, fetched_at)
        except (LookupError, ValueError, CninfoError, OSError) as exc:
            failures.append(f"{code}: {exc}")
            continue
        results.append(
            SyncResult(
                code=code,
                short_name=company["short_name"],
                column=company["column"],
                org_id=company["org_id"],
                start=window_start.isoformat(),
                end=window_end.isoformat(),
                rows=stored,
                skipped=False,
                message=(
                    f"{code} {company['short_name']} column={company['column']} "
                    f"orgId={company['org_id']} {window_start.isoformat()}~{window_end.isoformat()} "
                    f"写入 {stored} 条"
                ),
            )
        )

    if failures:
        done = "；".join(item.message for item in results)
        detail = "；".join(failures)
        prefix = f"已完成: {done}。" if done else ""
        raise RuntimeError(prefix + "失败: " + detail)
    return results
