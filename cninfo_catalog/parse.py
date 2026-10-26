"""把巨潮 JSON 收成目录行。不访问网络。"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from cninfo_catalog.categories import CODE_TO_NAME, ALIASES

SHANGHAI = ZoneInfo("Asia/Shanghai")
STATIC_PREFIX = "http://static.cninfo.com.cn/"
_TAGS = re.compile(r"<[^>]*>")

# topSearch 的 type=shj 表示「沪深京」这一组，不是 hisAnnouncement 的 column。
_COLUMN_FIELDS = ("column", "market", "plate", "type")
_COLUMN_ALIASES = {
    "sse": "sse",
    "szse": "szse",
    "bj": "bj",
    "bse": "bj",
    "bjse": "bj",
    "bjs": "bj",
}


def clean_text(value: object) -> str:
    if value is None:
        return ""
    text = _TAGS.sub("", str(value)).replace("\xa0", " ")
    return " ".join(text.split())


def shanghai_date_from_millis(raw: object) -> str:
    """announcementTime 是毫秒时间戳，按 Asia/Shanghai 取日历日期。"""
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ValueError("announcementTime 为空")
        millis = int(text)
    elif isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"无法解析 announcementTime: {raw!r}")
    else:
        millis = int(raw)
    moment = datetime.fromtimestamp(millis / 1000.0, tz=SHANGHAI)
    return moment.date().isoformat()


def today_shanghai(now: datetime | None = None) -> date:
    moment = now if now is not None else datetime.now(SHANGHAI)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=SHANGHAI)
    return moment.astimezone(SHANGHAI).date()


def adjunct_url(path: object) -> str | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text or text.lower() == "null":
        return None
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return STATIC_PREFIX + text.lstrip("/")


def column_from_search_item(item: dict) -> str | None:
    """只接受接口已经给出的 sse / szse / bj。shj 这类分组名忽略。"""
    for key in _COLUMN_FIELDS:
        raw = item.get(key)
        if not isinstance(raw, str):
            continue
        mapped = _COLUMN_ALIASES.get(raw.strip().lower())
        if mapped:
            return mapped
    return None


def column_from_code(code: str) -> str:
    """topSearch 没有 column 时按代码区分。北交所含 43/83/87 和 92 新代码。"""
    if code.startswith(("4", "8", "92")):
        return "bj"
    if code.startswith("6") or code.startswith("900"):
        return "sse"
    return "szse"


def normalize_code(value: object) -> str:
    if isinstance(value, int) and not isinstance(value, bool):
        text = str(value)
    else:
        text = str(value).strip()
    if not text.isdigit() or not 1 <= len(text) <= 6:
        raise ValueError(f"股票代码需为 6 位数字: {value}")
    return text.zfill(6)


def pick_company(code: str, payload: object) -> dict:
    """选用 topSearch 返回的 orgId。不按市场规则拼 orgId。"""
    items = _search_items(payload)
    exact = [item for item in items if str(item.get("code", "")).zfill(6) == code or str(item.get("code", "")) == code]
    if not exact:
        exact = [item for item in items if str(item.get("code", "")).startswith(code)]
    if not exact:
        raise LookupError(f"{code} 的证券检索没有结果，已停止这只股票（不会自行拼 orgId）")

    def rank(item: dict) -> tuple[int, int]:
        category = str(item.get("category") or "")
        a_share = 0 if "A" in category else 1
        delisted = 1 if str(item.get("delisted") or "").lower() == "true" else 0
        return (a_share, delisted)

    chosen = sorted(exact, key=rank)[0]
    org_id = str(chosen.get("orgId") or chosen.get("orgid") or "").strip()
    if not org_id:
        raise LookupError(f"{code} 的证券检索没有返回 orgId，已停止这只股票（不会自行拼 orgId）")
    short_name = clean_text(chosen.get("zwjc") or chosen.get("shortname") or chosen.get("secName"))
    column = column_from_search_item(chosen) or column_from_code(code)
    return {
        "code": code,
        "org_id": org_id,
        "short_name": short_name,
        "column": column,
    }


def parse_announcement(
    item: dict,
    *,
    stock_code: str,
    short_name: str,
    filter_codes: list[str],
    fetched_at: str,
) -> dict:
    ann_id = item.get("announcementId")
    if ann_id is None or str(ann_id).strip() == "":
        raise ValueError("有一条公告没有 announcementId")
    ann_id = str(ann_id).strip()
    if item.get("announcementTime") is None or item.get("announcementTime") == "":
        raise ValueError(f"公告 {ann_id} 缺少 announcementTime")
    title = clean_text(item.get("announcementTitle")) or clean_text(item.get("shortTitle"))
    if not title:
        raise ValueError(f"公告 {ann_id} 缺少标题")
    sec_code = clean_text(item.get("secCode")) or stock_code
    if sec_code.isdigit():
        sec_code = sec_code.zfill(6)
    name = clean_text(item.get("secName")) or short_name
    category_name, category_code = _category_fields(item, filter_codes)
    return {
        "stock_code": sec_code,
        "short_name": name,
        "title": title,
        "announcement_date": shanghai_date_from_millis(item.get("announcementTime")),
        "category_name": category_name,
        "category_code": category_code,
        "announcement_id": ann_id,
        "adjunct_url": adjunct_url(item.get("adjunctUrl")),
        "fetched_at": fetched_at,
    }


def effective_window(
    start: date | None,
    end: date | None,
    watermark: date | None,
    incremental: bool,
    today: date,
) -> tuple[date, date] | None:
    """返回含首尾的同步区间。增量且已经同步到今天时返回 None。"""
    if incremental and watermark is not None:
        start = watermark + timedelta(days=1)
    elif start is None:
        raise ValueError("请提供 --start。只有这只股票已有水位时，增量同步才可以省略开始日期")
    if end is None:
        end = today
    if start > end:
        if incremental:
            return None
        raise ValueError(f"开始日期 {start.isoformat()} 晚于结束日期 {end.isoformat()}")
    return start, end


def _category_fields(item: dict, filter_codes: list[str]) -> tuple[str, str]:
    raw_name = clean_text(item.get("announcementTypeName"))
    mapped = ALIASES.get(raw_name, "")
    if len(filter_codes) == 1:
        code = mapped or filter_codes[0]
        name = raw_name or CODE_TO_NAME.get(filter_codes[0], "")
        return name, code
    if raw_name:
        return raw_name, mapped
    return "", ""


def _search_items(payload: object) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if payload.get("orgId") or payload.get("code"):
            return [payload]
        for key in ("data", "records", "list", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    raise ValueError("证券检索返回的不是公司列表")
