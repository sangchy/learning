"""巨潮目录查询。一次一个请求，请求之间默认间隔 1 秒。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from cninfo_catalog.parse import pick_company

TOP_SEARCH_URL = "http://www.cninfo.com.cn/new/information/topSearch/query"
QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
PAGE_SIZE = 30
MAX_PAGES = 200
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
REFERER = "http://www.cninfo.com.cn/"


class CninfoError(RuntimeError):
    pass


class CninfoClient:
    def __init__(self, interval: float = 1.0, sleep=time.sleep, opener=None, clock=time.monotonic):
        if interval < 0:
            raise ValueError("请求间隔不能为负")
        self.interval = interval
        self._sleep = sleep
        self._opener = opener or urllib.request.urlopen
        self._clock = clock
        self._last_finished: float | None = None

    def lookup_company(self, code: str) -> dict:
        payload = self.post_form(TOP_SEARCH_URL, {"keyWord": code, "maxNum": "10"})
        return pick_company(code, payload)

    def fetch_announcements(
        self,
        *,
        code: str,
        org_id: str,
        column: str,
        start: str,
        end: str,
        category: str,
        on_page=None,
    ) -> list[dict]:
        """按页取完一只股票在日期区间内的公告。不下载附件。"""
        rows: list[dict] = []
        page = 1
        while page <= MAX_PAGES:
            payload = self.post_form(
                QUERY_URL,
                {
                    "pageNum": str(page),
                    "pageSize": str(PAGE_SIZE),
                    "column": column,
                    "tabName": "fulltext",
                    "plate": "",
                    "stock": f"{code},{org_id}",
                    "searchkey": "",
                    "secid": "",
                    "category": category,
                    "trade": "",
                    "seDate": f"{start}~{end}",
                    "sortName": "",
                    "sortType": "",
                    "isHLtitle": "true",
                },
            )
            announcements, total, has_more = _page_meta(payload)
            rows.extend(announcements)
            if on_page is not None:
                on_page(page, len(announcements), len(rows), total)
            if not announcements:
                if has_more:
                    raise CninfoError(f"{code} 分页异常：hasMore 为真但本页为空")
                break
            if has_more is False:
                break
            if total is not None and len(rows) >= total:
                break
            if has_more is None and len(announcements) < PAGE_SIZE:
                break
            page += 1
        else:
            raise CninfoError(f"{code} 分页超过 {MAX_PAGES} 页，已停止，水位不前移")
        return rows

    def post_form(self, url: str, fields: dict) -> object:
        self._pace()
        data = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("User-Agent", USER_AGENT)
        request.add_header("Referer", REFERER)
        request.add_header("Accept", "application/json, text/plain, */*")
        request.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        request.add_header("Origin", "http://www.cninfo.com.cn")
        try:
            with self._opener(request, timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise CninfoError(f"HTTP {exc.code} {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise CninfoError(f"请求失败 {url}: {exc.reason}") from exc
        finally:
            self._last_finished = self._clock()
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise CninfoError(f"响应不是 JSON: {raw[:200]!r}") from exc

    def _pace(self) -> None:
        if self._last_finished is None or self.interval <= 0:
            return
        delay = self.interval - (self._clock() - self._last_finished)
        if delay > 0:
            self._sleep(delay)


def _page_meta(payload: object) -> tuple[list[dict], int | None, bool | None]:
    if not isinstance(payload, dict):
        raise CninfoError("公告接口返回的不是对象")
    if "announcements" not in payload and "totalAnnouncement" not in payload:
        raise CninfoError("公告接口缺少 announcements / totalAnnouncement")
    announcements = payload.get("announcements") or []
    if not isinstance(announcements, list):
        raise CninfoError("announcements 不是数组")
    rows = [item for item in announcements if isinstance(item, dict)]
    total = payload.get("totalAnnouncement")
    if total is None:
        total = payload.get("totalRecordNum")
    if total is not None:
        total = int(total)
    has_more = payload.get("hasMore")
    if has_more is not None:
        has_more = bool(has_more)
    return rows, total, has_more
