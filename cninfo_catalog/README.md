# 巨潮公告目录（第一期）

个人研究用的本地小工具。按自选股、公告类别和起止日期，把巨潮资讯网的公告目录写进 SQLite。

这一期只存目录：股票代码、简称、标题、上海时区的公告日期、类别、公告编号，以及查询当时的附件地址。不下载 PDF 或网页正文，也不做本地模型分类。

请保持大约 1 秒的请求间隔，一次只发一个请求。不要用来做批量分发。

## 安装

需要 Python 3.9 或更高版本。第一期只用标准库。

```bash
pip install -r cninfo_catalog/requirements.txt
```

在仓库根目录运行下面的命令。

## 同步一小段

```bash
python -m cninfo_catalog sync --start 2026-10-13 --end 2026-10-26 --codes 000001 --categories all
```

`--codes` 和 `--categories` 会覆盖配置文件。类别可以多选，用逗号分隔；发给网站时会把类别代码用分号拼起来。不写类别、写成空、`all` 或 `全部`，表示不按类别过滤。

省略 `--end` 时，结束日期是今天（Asia/Shanghai）。

增量同步从这只股票上次成功的结束日期的后一天，一直补到结束日期：

```bash
python -m cninfo_catalog sync --start 2024-01-01 --incremental --codes 000001
```

第一次还没有水位，所以要给 `--start`。之后同一只股票可以省略 `--start`。

## 查看

```bash
python -m cninfo_catalog list --code 000001
python -m cninfo_catalog list --code 000001 --category 年度报告 --start 2026-01-01 --end 2026-10-26
```

不限类别时，接口经常不返回类别名称，目录里的类别列会是空的。同步时如果只选了一个类别，会把这个类别记下来。

## 文件在哪

- 自选股和默认类别：`cninfo_catalog/watchlist.json`。里面有示例代码 000001、600519、300750，可以直接改。
- 数据库：运行目录下的 `data/announcements.sqlite`（已在 `.gitignore` 里）。可以用 `--db` 换路径。

可用的类别名包括：年度报告、半年度报告、一季度报告、三季度报告、董事会、股东大会、股权变动、澄清风险业绩预告。年报、半年报、一季报、三季报、股东会，以及澄清致歉、风险提示、业绩预告也可以。

2026-10-26 实测，单独使用「澄清风险业绩预告」（`category_cqfxyj_szsh`）时，000001 在 2026-01-01 至 2026-10-26 的条数与不筛选相同。需要收窄时，改用上面拆开的三个名称。

## 还不在这一期

批量下载 PDF、保存正文，以及用本地模型做二级分类，都留到后面。附件地址只在查询时记下，程序不会去打开它。有些旧的 finalpage 链接会 404，稳定的键是公告编号。

## 测试

```bash
python -m unittest cninfo_catalog.tests.test_catalog
```

测试使用合成 JSON，不访问巨潮。
