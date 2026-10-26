"""命令行：sync 写入目录，list 从 SQLite 读出。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from cninfo_catalog.categories import resolve_category_query
from cninfo_catalog.client import CninfoClient, CninfoError
from cninfo_catalog.config import default_watchlist_path, load_watchlist
from cninfo_catalog.parse import SHANGHAI, normalize_code, today_shanghai
from cninfo_catalog.store import CatalogStore
from cninfo_catalog.sync import run_sync


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cninfo_catalog",
        description="把巨潮资讯网的 A 股公告目录保存到本地 SQLite。不下载 PDF。",
    )
    parser.add_argument(
        "--db",
        default="data/announcements.sqlite",
        help="SQLite 路径，默认 data/announcements.sqlite",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="按自选股和日期拉取公告目录")
    sync.add_argument("--start", help="开始日期 YYYY-MM-DD。增量且已有水位时可以省略")
    sync.add_argument("--end", help="结束日期 YYYY-MM-DD，默认今天（Asia/Shanghai）")
    sync.add_argument("--codes", help="逗号分隔的 6 位代码，覆盖配置文件")
    sync.add_argument(
        "--categories",
        help="逗号分隔的类别别名，覆盖配置文件。all 或空表示不筛选",
    )
    sync.add_argument(
        "--config",
        default=str(default_watchlist_path()),
        help="自选股 JSON，默认包内 watchlist.json",
    )
    sync.add_argument(
        "--incremental",
        action="store_true",
        help="从每只股票上次成功结束日期的后一天同步到结束日期",
    )

    listing = sub.add_parser("list", help="打印已保存的公告目录")
    listing.add_argument("--code", required=True, help="6 位股票代码")
    listing.add_argument("--category", help="类别别名或类别代码")
    listing.add_argument("--start", help="公告日期起 YYYY-MM-DD")
    listing.add_argument("--end", help="公告日期止 YYYY-MM-DD")

    args = parser.parse_args(argv)
    try:
        if args.command == "sync":
            return _sync(args)
        return _list(args)
    except (CninfoError, ValueError, LookupError, RuntimeError, OSError, sqlite3.Error) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        return 0


def _sync(args: argparse.Namespace) -> int:
    need_config = args.codes is None or args.categories is None
    config = load_watchlist(args.config) if need_config else None
    if args.codes is None:
        codes = config["codes"]
    else:
        codes = _parse_codes(args.codes)
    if args.categories is None:
        categories = config["categories"]
    else:
        categories = _parse_categories(args.categories)
    start = _parse_cli_date(args.start, "--start") if args.start else None
    end = _parse_cli_date(args.end, "--end") if args.end else None
    client = CninfoClient(interval=1.0)
    with CatalogStore(args.db) as store:
        results = run_sync(
            client=client,
            store=store,
            codes=codes,
            categories=categories,
            start=start,
            end=end,
            incremental=args.incremental,
            today=today_shanghai(),
            now=datetime.now(SHANGHAI),
        )
    if not results:
        print("没有需要同步的股票")
        return 0
    for item in results:
        print(item.message)
    written = sum(item.rows for item in results if not item.skipped)
    print(f"合计写入 {written} 条")
    return 0


def _list(args: argparse.Namespace) -> int:
    code = normalize_code(args.code)
    start = args.start
    end = args.end
    if start:
        _parse_cli_date(start, "--start")
    if end:
        _parse_cli_date(end, "--end")
    category_code = None
    category_names = None
    if args.category:
        category_code, category_names = resolve_category_query(args.category)
    if not Path(args.db).exists():
        _print_rows([])
        return 0
    with CatalogStore(args.db) as store:
        rows = store.list_announcements(
            code,
            category_code=category_code,
            category_names=category_names,
            start=start,
            end=end,
        )
    _print_rows(rows)
    return 0


def _print_rows(rows: list[dict]) -> None:
    headers = ["公告日期", "代码", "简称", "类别", "类别代码", "标题", "公告编号", "附件地址"]
    print("\t".join(headers))
    for row in rows:
        print(
            "\t".join(
                [
                    row["announcement_date"],
                    row["stock_code"],
                    row["short_name"],
                    row["category_name"],
                    row["category_code"],
                    row["title"],
                    row["announcement_id"],
                    row["adjunct_url"] or "",
                ]
            )
        )
    print(f"共 {len(rows)} 条")


def _parse_codes(text: str) -> list[str]:
    codes = [normalize_code(part) for part in text.split(",") if part.strip()]
    if not codes:
        raise ValueError("请至少给出一个股票代码")
    return codes


def _parse_categories(text: str) -> list[str]:
    if text.strip() == "":
        return ["all"]
    return [part.strip() for part in text.split(",") if part.strip()]


def _parse_cli_date(text: str, flag: str):
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{flag} 需要是 YYYY-MM-DD") from exc
