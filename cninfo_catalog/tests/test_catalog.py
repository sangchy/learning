"""离线测试：解析、上海日期、类别拼接、按公告编号去重。不访问网络。"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from datetime import date
from pathlib import Path

from cninfo_catalog.categories import join_categories
from cninfo_catalog.client import QUERY_URL, TOP_SEARCH_URL, CninfoClient
from cninfo_catalog.config import load_watchlist
from cninfo_catalog.parse import (
    column_from_code,
    column_from_search_item,
    parse_announcement,
    pick_company,
    shanghai_date_from_millis,
    effective_window,
)
from cninfo_catalog.store import CatalogStore
from cninfo_catalog.sync import run_sync

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CatalogTests(unittest.TestCase):
    def test_shanghai_date_not_utc(self) -> None:
        # 2026-10-24 00:00 上海 = 2026-10-23 16:00 UTC。按 UTC 取日期会少一天。
        self.assertEqual(shanghai_date_from_millis(1792771200000), "2026-10-24")
        self.assertEqual(shanghai_date_from_millis(1704038400000), "2024-01-01")
        self.assertEqual(shanghai_date_from_millis(1704038399999), "2023-12-31")

    def test_parse_fixture_rows(self) -> None:
        payload = json.loads((FIXTURES / "announcement_page.json").read_text(encoding="utf-8"))
        first, second = [
            parse_announcement(
                item,
                stock_code="000001",
                short_name="平安银行",
                filter_codes=["category_ndbg_szsh"],
                fetched_at="2026-10-26T12:00:00+08:00",
            )
            for item in payload["announcements"]
        ]
        self.assertEqual(first["announcement_date"], "2026-10-24")
        self.assertEqual(first["announcement_id"], "1225620612")
        self.assertEqual(first["title"], "关联交易公告")
        self.assertEqual(first["category_name"], "年度报告")
        self.assertEqual(first["category_code"], "category_ndbg_szsh")
        self.assertEqual(
            first["adjunct_url"],
            "http://static.cninfo.com.cn/finalpage/2026-10-24/1225620612.PDF",
        )
        self.assertEqual(second["title"], "跨日公告")
        self.assertEqual(second["announcement_date"], "2023-12-31")
        self.assertIsNone(second["adjunct_url"])
        self.assertEqual(second["category_name"], "年度报告")

    def test_join_categories(self) -> None:
        self.assertEqual(
            join_categories(["年度报告", "股权变动"]),
            "category_ndbg_szsh;category_gqbd_szsh",
        )
        self.assertEqual(join_categories(["年报", "年度报告"]), "category_ndbg_szsh")
        self.assertEqual(join_categories([]), "")
        self.assertEqual(join_categories(None), "")
        self.assertEqual(join_categories(["all"]), "")
        self.assertEqual(join_categories(["全部"]), "")
        self.assertEqual(join_categories(["category_dshgg_szsh"]), "category_dshgg_szsh")
        with self.assertRaises(ValueError):
            join_categories(["不存在的类别"])
        with self.assertRaises(ValueError):
            join_categories(["年度报告", "all"])

    def test_org_id_comes_from_top_search(self) -> None:
        payload = json.loads((FIXTURES / "top_search.json").read_text(encoding="utf-8"))
        company = pick_company("000001", payload)
        self.assertEqual(company["org_id"], "gssz0000001")
        self.assertEqual(company["short_name"], "平安银行")
        self.assertEqual(company["column"], "szse")
        self.assertIsNone(column_from_search_item(payload[0]))

        ningde = pick_company(
            "300750",
            [{
                "code": "300750",
                "orgId": "GD165627",
                "zwjc": "宁德时代",
                "category": "A股",
                "type": "shj",
            }],
        )
        self.assertEqual(ningde["org_id"], "GD165627")
        self.assertEqual(ningde["column"], "szse")

    def test_column_mapping(self) -> None:
        self.assertEqual(column_from_code("000001"), "szse")
        self.assertEqual(column_from_code("300750"), "szse")
        self.assertEqual(column_from_code("600519"), "sse")
        self.assertEqual(column_from_code("688265"), "sse")
        self.assertEqual(column_from_code("900904"), "sse")
        self.assertEqual(column_from_code("920946"), "bj")
        self.assertEqual(column_from_code("830946"), "bj")
        self.assertEqual(column_from_code("430001"), "bj")
        self.assertEqual(column_from_search_item({"type": "shj", "column": "bj"}), "bj")

    def test_upsert_dedupes_on_announcement_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(Path(tmp) / "announcements.sqlite")
            row = {
                "stock_code": "000001",
                "short_name": "平安银行",
                "title": "第一版标题",
                "announcement_date": "2026-10-24",
                "category_name": "董事会",
                "category_code": "category_dshgg_szsh",
                "announcement_id": "1225620612",
                "adjunct_url": "http://static.cninfo.com.cn/finalpage/2026-10-24/1225620612.PDF",
                "fetched_at": "2026-10-26T12:00:00+08:00",
            }
            other = dict(row, announcement_id="1225620999", title="另一条")
            store.upsert_announcements([row, other])
            self.assertEqual(store.count(), 2)
            store.upsert_announcements([dict(row, title="更新后的标题")])
            self.assertEqual(store.count(), 2)
            listed = store.list_announcements("000001")
            titles = {item["announcement_id"]: item["title"] for item in listed}
            self.assertEqual(titles["1225620612"], "更新后的标题")
            self.assertEqual(titles["1225620999"], "另一条")
            board = store.list_announcements(
                "000001",
                category_code="category_dshgg_szsh",
                category_names=["董事会"],
            )
            self.assertEqual(len(board), 2)
            store.close()

    def test_watermark_moves_forward_only(self) -> None:
        self.assertEqual(
            effective_window(date(2026, 10, 13), date(2026, 10, 26), None, False, date(2026, 10, 26)),
            (date(2026, 10, 13), date(2026, 10, 26)),
        )
        self.assertEqual(
            effective_window(date(2020, 1, 1), None, date(2026, 10, 20), True, date(2026, 10, 26)),
            (date(2026, 10, 21), date(2026, 10, 26)),
        )
        self.assertIsNone(
            effective_window(date(2020, 1, 1), None, date(2026, 10, 26), True, date(2026, 10, 26))
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(Path(tmp) / "announcements.sqlite")
            store.advance_watermark("000001", date(2026, 10, 20), "2026-10-20T00:00:00+08:00")
            store.advance_watermark("000001", date(2026, 10, 1), "2026-10-01T00:00:00+08:00")
            self.assertEqual(store.get_watermark("000001"), date(2026, 10, 20))
            store.advance_watermark("000001", date(2026, 10, 26), "2026-10-26T00:00:00+08:00")
            self.assertEqual(store.get_watermark("000001"), date(2026, 10, 26))
            store.close()

    def test_client_paginates_and_waits(self) -> None:
        page = json.loads((FIXTURES / "announcement_page.json").read_text(encoding="utf-8"))
        first = dict(page, announcements=[page["announcements"][0]], totalAnnouncement=2, hasMore=True)
        second = dict(page, announcements=[page["announcements"][1]], totalAnnouncement=2, hasMore=False)
        top = json.loads((FIXTURES / "top_search.json").read_text(encoding="utf-8"))
        bodies = [top, first, second]
        calls = []
        slept = []

        class Clock:
            def __init__(self) -> None:
                self.now = 0.0

            def __call__(self) -> float:
                return self.now

        clock = Clock()

        def sleep(seconds: float) -> None:
            slept.append(seconds)
            clock.now += seconds

        class Response:
            def __init__(self, payload: object) -> None:
                self._raw = json.dumps(payload).encode("utf-8")

            def read(self) -> bytes:
                return self._raw

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args) -> bool:
                return False

        def opener(request, timeout=30):
            self.assertEqual(request.get_header("Referer"), "http://www.cninfo.com.cn/")
            self.assertIn("Mozilla/5.0", request.get_header("User-agent"))
            calls.append(
                urllib.parse.parse_qs(request.data.decode("utf-8"), keep_blank_values=True)
            )
            return Response(bodies[len(calls) - 1])

        client = CninfoClient(interval=1.0, sleep=sleep, opener=opener, clock=clock)
        company = client.lookup_company("000001")
        rows = client.fetch_announcements(
            code=company["code"],
            org_id=company["org_id"],
            column=company["column"],
            start="2026-10-13",
            end="2026-10-26",
            category="category_ndbg_szsh;category_gqbd_szsh",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(slept, [1.0, 1.0])
        self.assertEqual(calls[0]["keyWord"], ["000001"])
        self.assertEqual(calls[1]["pageNum"], ["1"])
        self.assertEqual(calls[1]["pageSize"], ["30"])
        self.assertEqual(calls[1]["column"], ["szse"])
        self.assertEqual(calls[1]["stock"], ["000001,gssz0000001"])
        self.assertEqual(calls[1]["category"], ["category_ndbg_szsh;category_gqbd_szsh"])
        self.assertEqual(calls[1]["seDate"], ["2026-10-13~2026-10-26"])
        self.assertEqual(calls[1]["plate"], [""])
        self.assertEqual(calls[1]["searchkey"], [""])
        self.assertEqual(calls[1]["secid"], [""])
        self.assertEqual(calls[1]["trade"], [""])
        self.assertEqual(calls[1]["sortName"], [""])
        self.assertEqual(calls[1]["sortType"], [""])
        self.assertEqual(calls[2]["pageNum"], ["2"])

    def test_sync_writes_rows_and_skips_when_caught_up(self) -> None:
        page = json.loads((FIXTURES / "announcement_page.json").read_text(encoding="utf-8"))
        top = json.loads((FIXTURES / "top_search.json").read_text(encoding="utf-8"))
        calls = {"n": 0}

        class Response:
            def __init__(self, payload: object) -> None:
                self._raw = json.dumps(payload).encode("utf-8")

            def read(self) -> bytes:
                return self._raw

            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *args) -> bool:
                return False

        def opener(request, timeout=30):
            calls["n"] += 1
            url = request.full_url
            if url == TOP_SEARCH_URL:
                return Response(top)
            if url == QUERY_URL:
                return Response(page)
            raise AssertionError(url)

        client = CninfoClient(interval=0, sleep=lambda seconds: None, opener=opener)
        with tempfile.TemporaryDirectory() as tmp:
            store = CatalogStore(Path(tmp) / "announcements.sqlite")
            results = run_sync(
                client=client,
                store=store,
                codes=["000001"],
                categories=["all"],
                start=date(2026, 10, 13),
                end=date(2026, 10, 26),
                incremental=False,
                today=date(2026, 10, 26),
            )
            self.assertEqual(results[0].rows, 2)
            self.assertEqual(store.count(), 1 + 1)
            self.assertEqual(store.get_watermark("000001"), date(2026, 10, 26))
            calls_after_first = calls["n"]
            again = run_sync(
                client=client,
                store=store,
                codes=["000001"],
                categories=[],
                start=date(2020, 1, 1),
                end=None,
                incremental=True,
                today=date(2026, 10, 26),
            )
            self.assertTrue(again[0].skipped)
            self.assertEqual(calls["n"], calls_after_first)
            self.assertEqual(store.count(), 2)
            store.close()

    def test_shipped_watchlist(self) -> None:
        config = load_watchlist()
        self.assertEqual(config["codes"], ["000001", "600519", "300750"])
        joined = join_categories(config["categories"])
        self.assertIn("category_ndbg_szsh", joined)
        self.assertIn("category_cqfxyj_szsh", joined)
        self.assertIn(";", joined)


if __name__ == "__main__":
    unittest.main()
