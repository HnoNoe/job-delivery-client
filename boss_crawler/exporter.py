# -*- coding: utf-8 -*-
"""
exporter.py —— 导出 Excel / CSV
================================
生成一个多工作表的 Excel：
    采集说明 / 岗位明细 / 分类统计 / 二级分类 / 城市统计 /
    薪资分布 / 技能热度 / 公司招聘量 / 经验与学历
其中 分类统计、城市统计、技能热度 三张带柱状图，打开就能看。

「岗位明细」28 列，已开启筛选，岗位链接可点。
另出 CSV；文件被 Excel 占用时自动改存成「原名_时间戳」。
"""

import csv
import json
import re
from datetime import datetime
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent
SITE = "https://www.zhipin.com"

HEADER_FILL = "2F5597"
TITLE_COLOR = "1F3864"
NOTE_COLOR = "C00000"
BORDER_COLOR = "D9D9D9"

# 岗位明细：列名 -> (宽度, 取值字段)
DETAIL_COLUMNS = [
    ("序号", 6, None),
    ("岗位名称", 30, "岗位名称"),
    ("单位名称", 30, "单位名称"),
    ("薪资", 15, "薪资"),
    ("月薪下限K", 11, "_salary_min"),
    ("月薪上限K", 11, "_salary_max"),
    ("月薪中值K", 11, "_salary_mid"),
    ("年薪估算(万)", 13, "_salary_annual"),
    ("薪资档位", 12, "_salary_band"),
    ("城市", 10, "城市"),
    ("区域", 12, "区域"),
    ("商圈", 14, "商圈"),
    ("经验要求", 11, "经验"),
    ("经验档位", 11, "_exp_level"),
    ("学历要求", 10, "学历"),
    ("行业", 22, "行业"),
    ("公司规模", 13, "公司规模"),
    ("融资阶段", 12, "融资阶段"),
    ("HR", 10, "HR"),
    ("HR职位", 12, "HR职位"),
    ("技能标签", 34, "技能"),
    ("技能数", 8, "_skill_count"),
    ("搜索关键词", 12, "关键词"),
    ("采集时间", 19, "采集时间"),
    ("岗位ID", 28, "岗位ID"),
    ("岗位链接", 48, "岗位链接"),
    ("链接(可点)", 10, "_link"),
    ("数据来源", 22, "_source"),
]

NUMERIC_FIELDS = {"_salary_min", "_salary_max", "_salary_mid", "_salary_annual", "_skill_count"}
LINK_FIELD = "_link"

_SALARY_K = re.compile(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*[Kk千]")
_SALARY_K_ONE = re.compile(r"(\d+(?:\.\d+)?)\s*[Kk千]\s*以上")
_SALARY_MONTHS = re.compile(r"·\s*(\d+)\s*薪")
_SALARY_DAY = re.compile(r"(\d+)\s*-\s*(\d+)\s*元\s*/\s*天")
_SALARY_HOUR = re.compile(r"(\d+)\s*-\s*(\d+)\s*元\s*/\s*(?:时|小时)")
_SALARY_YUAN = re.compile(r"(\d+)\s*-\s*(\d+)\s*元\s*/\s*月")


def _styles():
    """样式对象统一在这里建（openpyxl 的样式不能跨 workbook 复用）。"""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color=BORDER_COLOR)
    return {
        "head_fill": PatternFill("solid", fgColor=HEADER_FILL),
        "head_font": Font(name="微软雅黑", size=10, bold=True, color="FFFFFF"),
        "title_font": Font(name="微软雅黑", size=14, bold=True, color=TITLE_COLOR),
        "note_font": Font(name="微软雅黑", size=10, color=NOTE_COLOR),
        "body_font": Font(name="微软雅黑", size=10),
        "bold_font": Font(name="微软雅黑", size=10, bold=True),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
        "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "left": Alignment(horizontal="left", vertical="center", wrap_text=True),
        "top": Alignment(vertical="top", wrap_text=True),
        "link_font": Font(name="微软雅黑", size=10, color="0563C1", underline="single"),
    }


# ---------------------------------------------------------------------------
# 字段加工
# ---------------------------------------------------------------------------
def salary_parts(text):
    """把「15-25K·14薪」这类描述拆成 (下限K, 上限K, 月数, 档位)。

    非月薪制（元/天、元/时、元/月）保留档位说明，K 值不参与平均统计。
    """
    raw = str(text or "").strip()
    months = 12
    found = _SALARY_MONTHS.search(raw)
    if found:
        try:
            months = int(found.group(1))
        except ValueError:
            months = 12
    match = _SALARY_K.search(raw)
    if match:
        low, high = float(match.group(1)), float(match.group(2))
        return low, high, months, _band(low, high)
    one = _SALARY_K_ONE.search(raw)
    if one:
        low = float(one.group(1))
        return low, low, months, _band(low, low)
    day = _SALARY_DAY.search(raw)
    if day:
        return 0.0, 0.0, months, "按天计薪"
    hour = _SALARY_HOUR.search(raw)
    if hour:
        return 0.0, 0.0, months, "按小时计薪"
    yuan = _SALARY_YUAN.search(raw)
    if yuan:
        low, high = float(yuan.group(1)) / 1000, float(yuan.group(2)) / 1000
        return low, high, months, _band(low, high)
    return 0.0, 0.0, months, "面议/未标注"


def _band(low, high):
    if low <= 0 and high <= 0:
        return "面议/未标注"
    mid = (low + high) / 2 if high else low
    if mid < 10:
        return "10K 以下"
    if mid < 15:
        return "10-15K"
    if mid < 20:
        return "15-20K"
    if mid < 30:
        return "20-30K"
    if mid < 50:
        return "30-50K"
    return "50K 以上"


def _exp_level(text):
    raw = str(text or "")
    if "应届" in raw or "在校" in raw:
        return "应届/在校"
    if "不限" in raw or not raw:
        return "经验不限"
    if "1年以内" in raw or "1-3" in raw:
        return "1-3年"
    if "3-5" in raw:
        return "3-5年"
    if "5-10" in raw:
        return "5-10年"
    if "10年" in raw:
        return "10年以上"
    return raw


def _value(record, field, index=None):
    if field is None:
        return index
    raw = record.get(field, "")
    if isinstance(raw, (list, tuple)):
        return " / ".join(str(x) for x in raw if x)
    return "" if raw is None else raw


def _prepare(record):
    """给一条记录补上派生字段，返回新 dict。"""
    row = dict(record)
    low, high, months, band = salary_parts(record.get("薪资"))
    row["_salary_min"] = round(low, 1) if low else ""
    row["_salary_max"] = round(high, 1) if high else ""
    row["_salary_mid"] = round((low + high) / 2, 1) if (low or high) else ""
    row["_salary_annual"] = round((low + high) / 2 * months / 10, 1) if (low or high) else ""
    row["_salary_band"] = band
    row["_exp_level"] = _exp_level(record.get("经验"))
    skills = [s for s in str(record.get("技能") or "").replace("，", ",").split(",") if s.strip()]
    row["_skill_count"] = len(skills)
    link = str(record.get("岗位链接") or "")
    row["_link"] = (SITE + link) if link.startswith("/") else link
    row["_source"] = record.get("_source") or "BOSS直聘（CDP 旁听）"
    return row


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------
def _counter(records, field, limit=None, key_fn=None):
    counts = {}
    for rec in records:
        key = key_fn(rec) if key_fn else str(rec.get(field) or "").strip()
        if not key:
            continue
        for part in (key.split(",") if field == "技能" else [key]):
            part = part.strip()
            if part:
                counts[part] = counts.get(part, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return rows[:limit] if limit else rows


def compute_stats(records):
    """算出各张统计表需要的数据。"""
    prepared = [_prepare(r) for r in records]
    mids = [p["_salary_mid"] for p in prepared if isinstance(p["_salary_mid"], (int, float)) and p["_salary_mid"]]
    mids_sorted = sorted(mids)
    median = 0
    if mids_sorted:
        mid_idx = len(mids_sorted) // 2
        median = (mids_sorted[mid_idx] if len(mids_sorted) % 2
                  else (mids_sorted[mid_idx - 1] + mids_sorted[mid_idx]) / 2)
    overall = {
        "岗位总数": len(prepared),
        "有效薪资样本": len(mids),
        "平均月薪K": round(sum(mids) / len(mids), 1) if mids else 0,
        "月薪中位数K": round(median, 1) if mids else 0,
        "月薪最低K": round(min(mids), 1) if mids else 0,
        "月薪最高K": round(max(mids), 1) if mids else 0,
        "公司数": len({p.get("单位名称") for p in prepared if p.get("单位名称")}),
        "城市数": len({p.get("城市") for p in prepared if p.get("城市")}),
    }
    return {
        "prepared": prepared,
        "overall": overall,
        "行业": _counter(prepared, "行业", limit=20),
        "公司规模": _counter(prepared, "公司规模"),
        "城市": _counter(prepared, "城市", limit=20),
        "薪资档位": [(b, n, round(b_total, 1)) for b, n, b_total in _salary_bands(prepared)],
        "技能": _counter(prepared, "技能", limit=25),
        "公司招聘量": _counter(prepared, "单位名称", limit=20),
        "经验": _counter(prepared, "经验"),
        "学历": _counter(prepared, "学历"),
    }


def _salary_bands(prepared):
    """薪资档位 -> (档位, 数量, 平均中值K)，按档位顺序输出。"""
    order = ["10K 以下", "10-15K", "15-20K", "20-30K", "30-50K", "50K 以上",
             "按天计薪", "按小时计薪", "面议/未标注"]
    buckets = {}
    for row in prepared:
        band = row.get("_salary_band") or "面议/未标注"
        count, total = buckets.get(band, (0, 0.0))
        mid = row.get("_salary_mid")
        total += mid if isinstance(mid, (int, float)) else 0
        buckets[band] = (count + 1, total)
    out = []
    for band in order:
        if band in buckets:
            count, total = buckets[band]
            out.append((band, count, total / count if count else 0))
    for band, (count, total) in buckets.items():
        if band not in order:
            out.append((band, count, total / count if count else 0))
    return out


# ---------------------------------------------------------------------------
# 写表
# ---------------------------------------------------------------------------
def _write_table(ws, headers, widths, rows, st, start_row=1, freeze=True,
                 numeric=frozenset(), link_col=None, as_number_format="0.0"):
    from openpyxl.utils import get_column_letter

    for col, (name, width) in enumerate(zip(headers, widths), 1):
        cell = ws.cell(row=start_row, column=col, value=name)
        cell.fill = st["head_fill"]
        cell.font = st["head_font"]
        cell.alignment = st["center"]
        cell.border = st["border"]
        ws.column_dimensions[get_column_letter(col)].width = width

    for r, row in enumerate(rows, start_row + 1):
        for col, val in enumerate(row, 1):
            cell = ws.cell(row=r, column=col, value=val)
            cell.font = st["body_font"]
            cell.border = st["border"]
            cell.alignment = st["center"] if isinstance(val, (int, float)) else st["left"]
            if col in numeric and isinstance(val, (int, float)) and val != "":
                cell.number_format = as_number_format

    if link_col and rows:
        for r in range(start_row + 1, start_row + 1 + len(rows)):
            cell = ws.cell(row=r, column=link_col)
            target = cell.value
            if isinstance(target, str) and target.startswith("http"):
                cell.hyperlink = target
                cell.value = "打开"
                cell.font = st["link_font"]

    if freeze:
        ws.freeze_panes = ws.cell(row=start_row + 1, column=1)
    if rows:
        ws.auto_filter.ref = "A%d:%s%d" % (start_row, get_column_letter(len(headers)),
                                           start_row + len(rows))
    ws.row_dimensions[start_row].height = 26


def _add_bar_chart(ws, title, first_row, last_row, cat_col=1, val_col=2,
                   anchor="E2", y_title="岗位数"):
    from openpyxl.chart import BarChart, Reference

    chart = BarChart()
    chart.type = "bar"
    chart.title = title
    chart.y_axis.title = y_title
    chart.height = 9
    chart.width = 18
    data = Reference(ws, min_col=val_col, min_row=first_row - 1, max_row=last_row)
    cats = Reference(ws, min_col=cat_col, min_row=first_row, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.legend = None
    ws.add_chart(chart, anchor)


def _sheet_note(ws, stats, meta, st):
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 84
    ws["A1"] = "BOSS直聘 岗位采集结果"
    ws["A1"].font = st["title_font"]
    ws.merge_cells("A1:B1")

    overall = stats["overall"]
    months = meta.get("months", 12)
    lines = [
        ("生成时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("数据来源", meta.get("source", "BOSS直聘（www.zhipin.com）")),
        ("采集方式", meta.get("mode", "CDP 旁听：真实浏览器打开页面，只读取页面自身发出的请求")),
        ("采集参数", meta.get("params", "")),
        ("岗位总数", overall["岗位总数"]),
        ("公司数 / 城市数", "%d / %d" % (overall["公司数"], overall["城市数"])),
        ("有效薪资样本", overall["有效薪资样本"]),
        ("平均月薪", ("%s K/月" % overall["平均月薪K"]) if overall["平均月薪K"] else "—"),
        ("月薪中位数", ("%s K/月" % overall["月薪中位数K"]) if overall["月薪中位数K"] else "—"),
        ("月薪区间", ("%sK ~ %sK" % (overall["月薪最低K"], overall["月薪最高K"]))
         if overall["有效薪资样本"] else "—"),
        ("采集耗时", "%s 秒" % meta.get("elapsed", 0)),
        ("", ""),
        ("薪资口径", "按 BOSS 返回的「15-25K·14薪」拆成下限/上限/月数；"
                    "年薪 = 月薪中值 × 月数；「元/天」「元/时」不并入平均月薪，单独标注档位。"),
        ("去重口径", "按岗位链接（encryptJobId）去重，同一岗位在不同关键词下只保留一条。"),
        ("字段口径", "岗位名称/单位名称/薪资/城市/区域/经验/学历/行业/规模/融资/HR/技能 "
                    "全部来自搜索列表接口，未做人工改写。"),
        ("使用提示", "「岗位明细」已开启筛选，可按城市/薪资档位/经验自由筛；"
                    "分类统计、城市统计、技能热度三张表右侧带柱状图。"),
        ("合规提示", "仅供个人学习与求职分析，请控制采集频率、遵守网站 robots 与用户协议，"
                    "不要用于商业转售或大规模骚扰性抓取。"),
    ]
    row = 2
    for key, value in lines:
        row += 1
        kc = ws.cell(row=row, column=1, value=key)
        vc = ws.cell(row=row, column=2, value=value)
        kc.font = st["bold_font"]
        kc.alignment = st["top"]
        vc.font = st["body_font"]
        vc.alignment = st["top"]
        if key:
            ws.row_dimensions[row].height = 32 if len(str(value)) > 40 else 18
    note_row = row + 2
    ws.cell(row=note_row, column=1, value="说明").font = st["note_font"]
    ws.cell(row=note_row, column=2,
            value="薪资为 BOSS 页面展示区间，非 offer 实际金额；统计仅供参考。").font = st["note_font"]


def _sheet_stats(ws, st, title, rows, cat_name, val_name, chart_anchor="E2", y_title="岗位数"):
    _write_table(ws, [cat_name, val_name], [30, 12], rows, st)
    if len(rows) >= 2:
        _add_bar_chart(ws, title, 2, len(rows) + 1, anchor=chart_anchor, y_title=y_title)


def _save_with_fallback(save_fn, out_path, logger=None):
    """目标文件被 Excel 占用时，改存成「原名_时间戳」而不是直接失败。"""
    out_path = Path(out_path)
    try:
        save_fn(out_path)
        return out_path
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        alt = out_path.with_name("%s_%s%s" % (out_path.stem, stamp, out_path.suffix))
        save_fn(alt)
        if logger:
            logger.warning("%s 正被其他程序占用（可能正在 Excel 里打开），已改存为 %s"
                           % (out_path.name, alt.name))
        return alt


def export_excel(records, meta=None, out_path=None, logger=None):
    """生成多工作表 Excel，返回实际文件路径（可能是改存后的名字）。"""
    try:
        from openpyxl import Workbook
    except ImportError:
        if logger:
            logger.warning("没装 openpyxl，跳过 Excel 导出（pip install openpyxl）")
        return None

    meta = meta or {}
    stats = compute_stats(records)
    st = _styles()
    wb = Workbook()

    ws_note = wb.active
    ws_note.title = "采集说明"
    _sheet_note(ws_note, stats, meta, st)

    # 岗位明细
    ws = wb.create_sheet("岗位明细")
    headers = [c[0] for c in DETAIL_COLUMNS]
    widths = [c[1] for c in DETAIL_COLUMNS]
    rows = []
    for idx, row in enumerate(stats["prepared"], 1):
        line = []
        for name, _w, field in DETAIL_COLUMNS:
            line.append(_value(row, field, index=idx))
        rows.append(line)
    link_col = headers.index("链接(可点)") + 1
    numeric_cols = {i + 1 for i, c in enumerate(DETAIL_COLUMNS) if c[2] in NUMERIC_FIELDS}
    _write_table(ws, headers, widths, rows, st, numeric=numeric_cols, link_col=link_col)

    # 分类统计（行业）
    _sheet_stats(wb.create_sheet("分类统计"), st, "行业岗位分布",
                 [[k, v] for k, v in stats["行业"]], "行业", "岗位数")
    # 二级分类（公司规模）
    _sheet_stats(wb.create_sheet("二级分类"), st, "公司规模分布",
                 [[k, v] for k, v in stats["公司规模"]], "公司规模", "岗位数")
    # 城市统计
    _sheet_stats(wb.create_sheet("城市统计"), st, "城市岗位分布",
                 [[k, v] for k, v in stats["城市"]], "城市", "岗位数")
    # 薪资分布
    ws = wb.create_sheet("薪资分布")
    _write_table(ws, ["薪资档位", "岗位数", "平均月薪K"],
                 [16, 12, 14], [[b, n, s] for b, n, s in stats["薪资档位"]], st, numeric={3})
    if len(stats["薪资档位"]) >= 2:
        _add_bar_chart(ws, "薪资档位分布", 2, len(stats["薪资档位"]) + 1)
    # 技能热度
    _sheet_stats(wb.create_sheet("技能热度"), st, "技能热度（出现岗位数）",
                 [[k, v] for k, v in stats["技能"]], "技能", "岗位数")
    # 公司招聘量
    _sheet_stats(wb.create_sheet("公司招聘量"), st, "公司在招岗位数",
                 [[k, v] for k, v in stats["公司招聘量"]], "公司", "岗位数", chart_anchor="F2")
    # 经验与学历
    ws = wb.create_sheet("经验与学历")
    _write_table(ws, ["经验要求", "岗位数"], [18, 12], [[k, v] for k, v in stats["经验"]], st)
    start = len(stats["经验"]) + 4
    ws.cell(row=start, column=1, value="学历要求").font = st["bold_font"]
    ws.cell(row=start, column=2, value="岗位数").font = st["bold_font"]
    for i, (k, v) in enumerate(stats["学历"], start + 1):
        ws.cell(row=i, column=1, value=k).font = st["body_font"]
        ws.cell(row=i, column=2, value=v).font = st["body_font"]

    path = Path(out_path or (ROOT / config.OUTPUT_XLSX))
    path.parent.mkdir(parents=True, exist_ok=True)
    return _save_with_fallback(wb.save, path, logger=logger)


# ---------------------------------------------------------------------------
# 其它输出
# ---------------------------------------------------------------------------
def save_raw(records, path=None):
    """写 JSONL（每行一条）。"""
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for item in records:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    return path


def load_raw(path=None):
    """读回 JSONL。"""
    path = Path(path or config.RAW_JSONL)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        return []
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:  # noqa: BLE001
                    continue
    return rows


def save_csv(records, path=None):
    """导出 CSV（UTF-8 BOM，Excel 直接打开不乱码）。"""
    path = Path(path or config.OUTPUT_CSV)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [c[0] for c in DETAIL_COLUMNS]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for idx, row in enumerate(records, 1):
            prepared = _prepare(row)
            writer.writerow([_value(prepared, field, index=idx) for _n, _w, field in DETAIL_COLUMNS])
    return path


def export_all(records, meta=None, logger=None):
    """一次导出 JSONL + CSV + XLSX，返回 {名称: 路径}。"""
    out = {
        "raw": save_raw(records, config.RAW_JSONL),
        "csv": save_csv(records, config.OUTPUT_CSV),
    }
    xlsx = export_excel(records, meta=meta, logger=logger)
    if xlsx:
        out["xlsx"] = xlsx
    return out
