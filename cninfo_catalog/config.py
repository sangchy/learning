"""自选股配置。命令行里的代码和类别覆盖这里的值。"""

from __future__ import annotations

import json
from pathlib import Path

from cninfo_catalog.parse import normalize_code

PACKAGE_DIR = Path(__file__).resolve().parent


def default_watchlist_path() -> Path:
    return PACKAGE_DIR / "watchlist.json"


def load_watchlist(path: str | Path | None = None) -> dict:
    config_path = Path(path) if path else default_watchlist_path()
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"找不到配置文件: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件不是 JSON: {config_path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("配置文件的顶层需要是对象")
    codes_raw = payload.get("codes") or []
    categories_raw = payload.get("categories") or []
    if isinstance(categories_raw, str):
        categories = [categories_raw]
    elif isinstance(categories_raw, list):
        categories = [str(item).strip() for item in categories_raw if str(item).strip()]
    else:
        raise ValueError("categories 需要是字符串数组")
    if not isinstance(codes_raw, list) or not codes_raw:
        raise ValueError("配置文件里的 codes 不能为空")
    return {
        "path": str(config_path),
        "codes": [normalize_code(item) for item in codes_raw],
        "categories": categories,
    }
