"""公告类别别名。空或 all 表示不向接口传类别。"""

from __future__ import annotations

# 名称按用户指定的叫法排列。同一代码的第一个名称是写入目录时用的规范名。
_CANONICAL = (
    ("年度报告", "category_ndbg_szsh"),
    ("半年度报告", "category_bndbg_szsh"),
    ("一季度报告", "category_yjdbg_szsh"),
    ("三季度报告", "category_sjdbg_szsh"),
    ("董事会", "category_dshgg_szsh"),
    ("股东大会", "category_gddh_szsh"),
    ("股权变动", "category_gqbd_szsh"),
    ("澄清风险业绩预告", "category_cqfxyj_szsh"),
)

# 站点当前菜单上的短名称，指向同一代码。
_EXTRA = (
    ("年报", "category_ndbg_szsh"),
    ("半年报", "category_bndbg_szsh"),
    ("一季报", "category_yjdbg_szsh"),
    ("三季报", "category_sjdbg_szsh"),
    ("股东会", "category_gddh_szsh"),
    ("澄清致歉", "category_cqdq_szsh"),
    ("风险提示", "category_fxts_szsh"),
    ("业绩预告", "category_yjygjxz_szsh"),
)

ALIASES = {name: code for name, code in (*_CANONICAL, *_EXTRA)}
CODE_TO_NAME = {}
for _name, _code in _CANONICAL:
    CODE_TO_NAME.setdefault(_code, _name)

_ALL = {"all", "全部", "*"}


def join_categories(values: list[str] | None) -> str:
    """把类别别名或类别代码拼成接口要的分号串。无筛选时返回空串。"""
    if not values:
        return ""
    codes: list[str] = []
    for raw in values:
        token = str(raw).strip()
        if not token:
            continue
        if token.lower() in _ALL or token in _ALL:
            if len([item for item in values if str(item).strip()]) > 1:
                raise ValueError("类别「全部」不能和其他类别一起选")
            return ""
        code = ALIASES.get(token)
        if code is None and token.startswith("category_"):
            code = token
        if code is None:
            known = "、".join(name for name, _ in _CANONICAL)
            raise ValueError(f"未知公告类别: {token}。可用: {known}，或 all")
        if code not in codes:
            codes.append(code)
    return ";".join(codes)


def names_for_code(code: str) -> list[str]:
    names = [name for name, mapped in ALIASES.items() if mapped == code]
    canonical = CODE_TO_NAME.get(code)
    if canonical and canonical not in names:
        names.insert(0, canonical)
    return names


def resolve_category_query(token: str) -> tuple[str, list[str]]:
    """列表筛选：返回类别代码，以及可匹配的类别名称。"""
    text = token.strip()
    if not text:
        raise ValueError("类别不能为空")
    code = ALIASES.get(text)
    if code is None and text.startswith("category_"):
        code = text
    if code is None:
        raise ValueError(f"未知公告类别: {text}")
    names = names_for_code(code)
    if text not in names:
        names.append(text)
    return code, names
