"""纯规则简历解析引擎（离线、零网络、零依赖）。

职责边界：
- 只做「文本 -> 结构化字段」：不调用模型接口、不读 Key、不依赖第三方库；
- 输出与 resume_ai.smart_parse 的 data 契约同构（L0 字段 + 意向岗位 + 技能 + 经历），
  parse() 额外返回 meta（引擎、告警、未映射内容、候选明细、覆盖范围）；
- 经历以「候选」为单位产出：稳定编号、来源行号、原文片段、分类依据，供 GUI 预览核对
  与 AI 结果按编号合并。

已知限制见 LIMITATIONS。本模块不修改任何全局状态，可被 GUI/CLI/测试同时调用。
"""
import re

import schema

LIMITATIONS = [
    "多栏版式若文本层已乱序，条目可能串段（无版式信息时只能按线性文本处理）",
    "扫描件/图片 PDF 无文字层，需先 OCR 才能进来",
    "「标题单独一行、日期在上/下一行」的模板可能漏切分",
    "日期只落在行首才视为新条目起点，行中出现日期不会切分",
    "不做表格重建，跨页断表按普通行处理",
]

# ---------------- 章节 ----------------

SECTION_ALIASES = {
    "教育": ["教育经历", "教育背景", "学习经历", "教育", "学历"],
    "学生工作": ["在校经历", "校园经历", "学生工作", "在校实践", "在校职务", "学生干部"],
    "工作": ["工作经历", "实习经历", "实习", "工作", "职业经历", "兼职经历"],
    "项目": ["科研&实践经历", "科研与实践经历", "科研经历", "科研项目", "项目经历",
             "实践经历", "社会实践", "科研&实践", "科研实践", "项目", "科研"],
    "技能": ["相关技能", "专业技能", "技能特长", "技能", "能力特长"],
    "证书荣誉": ["荣誉证书", "证书荣誉", "获奖情况", "所获荣誉", "荣誉奖项", "证书", "奖项"],
    "个人信息": ["个人信息", "基本信息", "联系方式", "个人资料"],
    "求职意向": ["求职意向", "求职目标", "意向岗位", "应聘意向"],
    "自我评价": ["自我评价", "个人评价", "自我介绍"],
}

_ALIAS_TO_SECTION = {}
for _sec, _aliases in SECTION_ALIASES.items():
    for _a in _aliases:
        _ALIAS_TO_SECTION.setdefault(_a, _sec)

_HEAD_NOISE = re.compile(r"[：:]\s*$")
_HEAD_TAIL = re.compile(r"[（(][^）)]{0,12}[）)]\s*$")

# 个人信息标签行：出现在任何章节之外都按标签抽取，并终止当前非个人章节的收集
INFO_LABEL = re.compile(
    r"^(?:政治面貌|民族|籍贯|现居|生日|出生日期|出生年月|手机|电话|邮箱|E-?mail|"
    r"求职意向|意向岗位|性别|身高|婚姻状况|身份证)\s*[：:]", re.I)

# 「证书：A、B」这类标签行本身即证书，即便不在「荣誉证书」章节下也要收
CERT_LABEL = re.compile(r"^(?:证书|资格证书|技能证书|语言能力|证书情况)\s*[：:]")


def _squash(line):
    """解析用归一：全角空格/NBSP/各种连字符统一，行首尾去空白。保留原始行另存。"""
    return (line.replace("\u3000", " ").replace("\xa0", " ")
                .replace("－", "-").replace("–", "-").replace("—", "-")
                .replace("～", "~").strip())


def section_of(line):
    """整行是否章节标题；是则返回章节名，否则 None。"""
    raw = _squash(line)
    if not raw or len(raw) > 16 or re.search(r"\d", raw):
        return None
    cand = _HEAD_NOISE.sub("", _HEAD_TAIL.sub("", raw)).replace(" ", "")
    if not cand:
        return None
    if cand in _ALIAS_TO_SECTION:
        return _ALIAS_TO_SECTION[cand]
    stripped = re.sub(r"^[一二三四五六七八九十0-9.、()（）\s]+", "", cand)
    return _ALIAS_TO_SECTION.get(stripped)


# ---------------- 日期 ----------------

_YM = r"\d{4}\s*[.\-/年]\s*\d{1,2}\s*月?"
_YEAR = r"\d{4}(?!\d)"
_SEP = r"(?:-|~|至|到)"
DATE_HEAD = re.compile(
    r"^(?P<start>" + _YM + r"|" + _YEAR + r")"
    r"\s*(?:" + _SEP + r"\s*(?P<end>至今|今|" + _YM + r"|" + _YEAR + r"))?"
    r"\s*[：:]?\s*(?P<title>.*)$")

_PRESENT = ("至今", "今", "现在", "在职")


def parse_date_token(tok):
    """(规范值, 精度, 告警)。年份保持 YYYY（不补月），非法月保留原文并告警。"""
    if not tok:
        return "", "", ""
    t = _squash(tok)
    if t in _PRESENT:
        return "至今", "present", ""
    m = re.match(r"^(\d{4})\s*[.\-/年]?\s*(\d{1,2})?\s*月?$", t)
    if not m:
        return t, "raw", "无法解析的日期：%s" % t
    year, mon = m.group(1), m.group(2)
    if not mon:
        return year, "year", ""
    mi = int(mon)
    if not 1 <= mi <= 12:
        return t, "invalid", "非法月份：%s（保留原文）" % t
    return "%s-%02d" % (year, mi), "month", ""


def _cmp(val):
    if not val:
        return None
    if val == "至今":
        return (9999, 12)
    m = re.match(r"^(\d{4})(?:-(\d{2}))?$", val)
    return (int(m.group(1)), int(m.group(2) or 0)) if m else None


# ---------------- 文本拼接 ----------------

_CJK = re.compile(r"[\u4e00-\u9fff]")


def join_lines(lines):
    """PDF 折行还原：中文直接相接，其余补一个空格，避免把词粘死。"""
    out = ""
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        if not out:
            out = s
            continue
        prev, nxt = out[-1], s[0]
        if _CJK.match(prev) and _CJK.match(nxt):
            out += s
        elif prev in "，。；：、）》”" or nxt in "，。；：、）（》":
            out += s
        else:
            out += " " + s
    return out


# ---------------- 类型 ----------------

TYPE_HINTS = [
    ("实习/工作", ("实习", "兼职", "全职", "在职")),
    ("学生工作", ("学生工作", "班委", "党支部", "团委", "学生会", "社团", "驻班", "先锋队")),
    ("竞赛", ("竞赛", "比赛", "大赛", "挑战赛")),
    ("专利", ("专利",)),
    ("论文", ("论文", "期刊", "见刊", "发表")),
    ("证书", ("证书", "资格证")),
    ("作品链接", ("作品集", "作品链接")),
]

TYPE_ALIAS = {
    "实习": "实习/工作", "工作": "实习/工作", "实习/工作": "实习/工作",
    "兼职": "实习/工作", "全职": "实习/工作",
    "项目": "项目", "项目经历": "项目", "科研": "项目", "科研项目": "项目",
    "实践": "项目", "社会实践": "项目",
    "竞赛": "竞赛", "比赛": "竞赛", "奖项": "竞赛",
    "论文": "论文", "专利": "专利", "证书": "证书",
    "学生工作": "学生工作", "校园经历": "学生工作", "在校经历": "学生工作",
    "作品链接": "作品链接", "作品": "作品链接",
}

SECTION_DEFAULT_TYPE = {"学生工作": "学生工作", "工作": "实习/工作", "项目": "项目"}


def normalize_type(raw, section=None, title=""):
    """类型归一：按明确依据判断；判不出返回空串（不默认成「项目」）。

    不做性质推断：科研/毕设 != 论文；校招/社区工作 != 实习/工作。
    标题里明确写「实习」时优先于章节默认（章节默认只兜底）。
    """
    s = (raw or "").strip()
    if s in TYPE_ALIAS:
        return TYPE_ALIAS[s]
    if s in schema.L1_TYPES:
        return s
    for t, words in TYPE_HINTS:
        if s and any(w in s for w in words):
            return t
    if title:
        for t, words in TYPE_HINTS:
            if any(w in title for w in words):
                return t
    return SECTION_DEFAULT_TYPE.get(section, "")


# ---------------- 名称 / 角色 ----------------

# 只认完整的角色复合词，逐字吞并会切出「理学院青年先锋队干事 -> 理学 / 院青年…」这类废名
ROLE_COMPOUNDS = [
    "宣传委员兼文娱委员", "副书记", "驻班党员", "宣传委员", "文娱委员", "组织委员",
    "学习委员", "体育委员", "负责人", "队长", "干事", "部长", "主席", "团支书",
    "班长", "实习生", "助理", "组长", "成员", "委员", "党员", "主管", "书记",
]
_ROLE_SORTED = sorted(ROLE_COMPOUNDS, key=len, reverse=True)


def _trailing_role(s):
    for r in _ROLE_SORTED:
        if s.endswith(r) and len(s) > len(r):
            return r
    return ""


def split_role(title):
    """(名称, 角色)。角色只在标题尾部是明确角色复合词时拆出，其余原样保留。"""
    s = (title or "").strip()
    if not s:
        return "", ""
    # 角色演变：A干事→负责人
    for arrow in ("→", "->"):
        if arrow in s:
            left, right = s.split(arrow, 1)
            l_role = _trailing_role(left.strip())
            r_ok = right.strip() and (right.strip() in ROLE_COMPOUNDS or _trailing_role(right.strip()))
            if l_role and r_ok:
                return left.strip()[:-len(l_role)].strip(), "%s→%s" % (l_role, right.strip())
    role = _trailing_role(s)
    if role:
        name = s[:-len(role)].strip(" ・·、-—")
        if name:
            return name, role
    return s, ""


# ---------------- 技能 / 工具 ----------------

SKILL_BANK = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "Go", "SQL", "MySQL", "Redis",
    "Linux", "Docker", "Git", "Spring", "Django", "Flask", "FastAPI",
    "Excel", "WPS", "Word", "PPT", "PowerPoint", "SPSS", "Origin", "Matlab",
    "Photoshop", "AutoCAD", "SolidWorks", "剪映", "Premiere",
    "豆包", "通义千问", "ChatGPT", "DeepSeek", "Kimi",
    "UV-Vis", "IR", "NMR", "XRD", "SEM", "TEM",
    "数据分析", "数据统计", "文案", "视频制作", "资料搜集", "英语",
]


SKILL_ALIAS = {
    "ppt": "PPT", "powerpoint": "PPT", "word": "Word", "excel": "Excel", "wps": "WPS",
    "sql": "SQL", "python": "Python", "cet-4": "CET-4", "cet-6": "CET-6",
}

_STOP_PREFIX = re.compile(
    r"^(?:熟练使用|熟练运用|熟练|精通|掌握|熟悉|了解|会使用|能使用|具备|使用|会用|可|能)\s*")
_STOP_SUFFIX = re.compile(r"\s*(?:等\s*[Aa][Ii]\s*工具|等工具|等相关技能|等技能|等等|等)\s*$")
_FRAGMENT_HINTS = ("具备", "能力", "进行", "辅助", "负责", "熟练", "掌握", "精通", "熟悉", "使用")


def _atomic_skill(tok):
    t = str(tok or "").strip(" 　·・,，;；。.、:：()（）【】")
    t = _STOP_PREFIX.sub("", t).strip()
    t = _STOP_SUFFIX.sub("", t).strip()
    return t


def normalize_skills(items, warnings=None, limit=60):
    """技能归一：拆短语 → 去动词前缀/后缀套话 → 只留「原子技能」→ 去重。

    接受三种形态：①技能库/别名命中；②纯英文/数字工具名（WPS、ChatGPT、UV-Vis）；
    ③短中文词（≤4 字、不含动词与碎片词）。其余按碎片丢弃并写 warnings，不静默吞。
    """
    warnings = warnings if warnings is not None else []
    bank = {s.lower(): s for s in SKILL_BANK}
    out, seen = [], set()
    for raw in items or []:
        if raw is None:
            continue
        for part in re.split(r"[、,，;；。！!?？/|\n]+", str(raw)):
            tok = _atomic_skill(part)
            if not tok:
                continue
            low = tok.lower()
            is_ascii = bool(re.fullmatch(r"[A-Za-z0-9+.#\-]+(?: [A-Za-z0-9+.#\-]+)*", tok))
            is_short_cjk = bool(re.fullmatch(r"[\u4e00-\u9fff]{3,4}", tok))
            fragment = any(h in tok for h in _FRAGMENT_HINTS) or bool(re.search(r"[的了和与等]", tok))
            if low in bank or low in SKILL_ALIAS:
                canon = SKILL_ALIAS.get(low) or bank[low]
            elif is_ascii:
                canon = tok
            elif is_short_cjk and not fragment:
                canon = tok
            else:
                warnings.append({"source": "skills",
                                 "message": "非原子技能，已丢弃：%s" % tok[:24]})
                continue
            key = canon.lower()
            if key in seen or any(a and a in key for a in seen):
                continue
            seen.add(key)
            out.append(canon)
    return out[:limit]


def _hits(text):
    low = (text or "").lower()
    out, seen = [], set()
    for s in SKILL_BANK:
        k = s.lower()
        if k in low and k not in seen:
            seen.add(k)
            out.append(s)
    return out


# ---------------- 切分 ----------------

def split_sections(lines):
    """-> [(section, [(lineno, raw_line), ...]), ...]；首个章节标题前记为 '_head'。"""
    blocks, cur_sec, cur = [], "_head", []
    for i, raw in enumerate(lines, 1):
        sec = section_of(raw)
        if sec:
            blocks.append((cur_sec, cur))
            cur_sec, cur = sec, []
        else:
            cur.append((i, raw))
    blocks.append((cur_sec, cur))
    return blocks


def entry_candidates(section, block):
    """经历段 -> 原始候选；以「行首日期 + 标题」为新条目起点。"""
    out, cur = [], None
    for lineno, raw in block:
        line = _squash(raw)
        if not line or INFO_LABEL.match(line):
            continue
        m = DATE_HEAD.match(line)
        if m and (m.group("title") or "").strip():
            if cur:
                out.append(cur)
            cur = {"section": section, "line": lineno,
                   "start_raw": m.group("start"), "end_raw": m.group("end") or "",
                   "raw_title": m.group("title").strip(), "body": []}
            continue
        if cur:
            cur["body"].append(raw)
    if cur:
        out.append(cur)
    return out


def build_row(cand, warnings, index):
    """原始候选 -> (L2 行, 候选明细)。事项保留原文，不做 200 字截断。"""
    title = cand["raw_title"]
    name, role = split_role(title)
    start, sprec, w1 = parse_date_token(cand["start_raw"])
    end, eprec, w2 = parse_date_token(cand["end_raw"])
    for w in (w1, w2):
        if w:
            warnings.append({"candidate": index, "line": cand["line"], "message": w})

    body = join_lines(cand["body"])
    etype = normalize_type("", cand["section"], title)
    if not etype:
        warnings.append({"candidate": index, "line": cand["line"],
                         "message": "类型无法判定，需人工核对：%s" % title})

    result = ""
    for sent in re.split(r"(?<=[。；])", body):
        if re.search(r"获评|荣获|获得|斩获|评为|被评为", sent):
            result = sent.strip("；。 ")
            break

    if not cand["end_raw"]:
        warnings.append({"candidate": index, "line": cand["line"],
                         "message": "结束时间原文缺失，按留空处理（未补造）：%s" % title})

    row = {
        "类型": etype, "名称": name, "角色": role,
        "时间起": start, "时间止": end,
        "事项": body, "结果": result,
        "技术工具": "、".join(_hits(body)), "挂靠": "", "证据": "",
    }
    detail = {
        "id": "R%02d" % index, "kind": "experience", "section": cand["section"],
        "line": cand["line"], "raw_title": title,
        "raw_date": (cand["start_raw"] + ("-" + cand["end_raw"] if cand["end_raw"] else "")),
        "start_precision": sprec, "end_precision": eprec,
        "fields": row,
        "reasons": ["章节=%s" % cand["section"], "标题角色词拆分" if role else "标题无角色后缀"],
    }
    return row, detail


def _cert_rows(block, warnings, unmapped, start_index, force_single=False):
    """证书/荣誉段：按顿号逗号拆分；荣誉类进未映射，不硬塞类型。

    force_single=True 用于「证书：X」这类标签行——即使只有一项也按证书收下。
    """
    rows, details = [], []
    for lineno, raw in block:
        line = _squash(raw)
        if not line:
            continue
        if INFO_LABEL.match(line):
            continue
        body = re.sub(r"^[^：:]{0,8}[：:]", "", line).strip()
        parts = [p.strip() for p in re.split(r"[、,，;；]", body) if p.strip()]
        if len(parts) <= 1:
            if force_single and body:
                parts = [body]
            else:
                unmapped.append({"section": "证书荣誉", "line": lineno,
                                 "text": line[:120], "reason": "无法拆分为独立条目"})
                continue
        for p in parts:
            m = re.match(r"^(?P<name>.+?)\s*[【\[]\s*(?P<score>\d{1,3})\s*[】\]]?$", p)
            name = (m.group("name") if m else p).strip()
            score = m.group("score") if m else ""
            if re.search(r"先进个人|优秀|标兵|三好|奖学金|荣誉", name) and not re.search(
                    r"证书|级|资格", name):
                unmapped.append({"section": "证书荣誉", "line": lineno, "text": name,
                                 "reason": "荣誉类，schema 无对应类型，未映射"})
                continue
            row = {k: "" for k in schema.L2_FIELDS}
            row.update({"类型": "证书", "名称": name, "事项": p,
                        "结果": ("成绩 %s" % score) if score else ""})
            rows.append(row)
            details.append({"id": "C%02d" % (start_index + len(rows)), "kind": "certificate",
                            "section": "证书荣誉", "line": lineno, "raw_title": p,
                            "fields": row, "reasons": ["章节=证书荣誉", "按顿号/逗号拆分"]})
    return rows, details


# ---------------- 主入口 ----------------

def parse(text):
    """规则解析 -> {"data": {...}, "meta": {...}}。不抛异常（内部异常降级为告警）。"""
    warnings, unmapped = [], []
    lines = (text or "").replace("\r\n", "\n").split("\n")
    # 「证书：A、B」独立成行时先摘出来，避免被上一条经历的正文吞掉
    standalone_certs, kept = [], []
    for i, raw in enumerate(lines, 1):
        if CERT_LABEL.match(_squash(raw)):
            standalone_certs.append((i, raw))
            kept.append("")
        else:
            kept.append(raw)
    blocks = split_sections(kept)
    flat = "\n".join(_squash(l) for l in lines)

    data = {}
    exp_rows, candidates = [], []

    # ---- 标签类基本信息（全篇扫描）----
    m = re.search(r"1[3-9]\d{9}", flat)
    if m:
        data["手机"] = m.group(0)
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", flat)
    if m:
        data["邮箱"] = m.group(0)
    for field in ("政治面貌", "民族", "籍贯", "现居", "学院"):
        m = re.search(field + r"\s*[：:]\s*([^\s，。；、:：]{1,20})", flat)
        if m:
            data[field] = m.group(1)
    m = re.search(r"(?:生日|出生日期|出生年月)\s*[：:]\s*(\d{4})\s*[.\-/年]\s*(\d{1,2})", flat)
    if m:
        data["出生日期"] = "%s-%02d" % (m.group(1), int(m.group(2)))
    m = re.search(r"(?:求职意向|意向岗位|应聘意向|求职目标)\s*[：:]\s*([^\s，。；]{1,30})", flat)
    if m:
        data["意向岗位"] = m.group(1)
    m = re.search(r"性别\s*[：:]\s*([男女])", flat)
    if m:
        data["性别"] = m.group(1)

    # ---- 姓名：首个短行，无数字/标签/句读 ----
    for raw in lines[:6]:
        s = _squash(raw)
        if not s or section_of(raw) or INFO_LABEL.match(s):
            continue
        if re.search(r"\d", s) or "：" in s or ":" in s or re.search(r"[，。；]", s):
            continue
        if 2 <= len(s) <= 6:
            data.setdefault("姓名", s)
            break

    # ---- 逐章节 ----
    for sec, block in blocks:
        if sec == "_head":
            continue
        if sec == "教育":
            for _lineno, raw in block:
                m = DATE_HEAD.match(_squash(raw))
                if m and (m.group("title") or "").strip():
                    title = m.group("title").strip()
                    data.setdefault("学校", title)
                    s, _, _ = parse_date_token(m.group("start"))
                    e, _, _ = parse_date_token(m.group("end") or "")
                    if re.match(r"^\d{4}", s or ""):
                        data.setdefault("入学年月", s)
                    if re.match(r"^\d{4}", e or ""):
                        data.setdefault("毕业年月", e)
                    break
            for _lineno, raw in block:
                line = _squash(raw)
                if "专业排名" in line:
                    warnings.append({"line": _lineno,
                                     "message": "出现「专业排名」，按规则不写入「专业」",
                                     "source": line[:40]})
                    continue
                mm = re.search(r"(?:所学专业|专业)\s*[：:]\s*([\u4e00-\u9fffa-zA-Z]{2,20})", line)
                if mm:
                    data.setdefault("专业", mm.group(1))
            continue
        if sec in ("学生工作", "工作", "项目"):
            for cand in entry_candidates(sec, block):
                row, detail = build_row(cand, warnings, len(exp_rows) + 1)
                exp_rows.append(row)
                candidates.append(detail)
            continue
        if sec == "技能":
            block_text = join_lines([raw for _l, raw in block])
            data["技能"] = normalize_skills(_hits(block_text), warnings)
            continue
        if sec == "证书荣誉":
            rows, details = _cert_rows(block, warnings, unmapped, len(exp_rows) + 1)
            exp_rows.extend(rows)
            candidates.extend(details)
            continue
        if sec in ("个人信息", "求职意向"):
            continue

    for lineno, raw in standalone_certs:
        rows, details = _cert_rows([(lineno, raw)], warnings, unmapped,
                                   len(exp_rows) + 1, force_single=True)
        exp_rows.extend(rows)
        candidates.extend(details)

    data["经历"] = exp_rows

    # ---- 全局校验 ----
    enroll = _cmp(data.get("入学年月", ""))
    for i, row in enumerate(exp_rows, 1):
        s, e = _cmp(row.get("时间起", "")), _cmp(row.get("时间止", ""))
        if s and e and s > e:
            warnings.append({"candidate": i, "message":
                             "起始时间晚于结束时间：%s" % row.get("名称", "")})
        if enroll and s and s < enroll and row.get("类型") in ("学生工作", "项目"):
            warnings.append({"candidate": i, "message":
                             "起始时间早于入学时间，请核对：%s" % row.get("名称", "")})
        if not row.get("事项"):
            warnings.append({"candidate": i, "message":
                             "该条无正文：%s" % row.get("名称", "")})

    meta = {
        "requested_mode": "rule",
        "used_engine": "rule",
        "ai_status": "not_requested",
        "warnings": warnings,
        "candidates": candidates,
        "unmapped_content": unmapped,
        "coverage": {"chars": len(text or ""), "lines": len(lines),
                     "sections": [b[0] for b in blocks if b[0] != "_head"],
                     "truncated": False},
        "limitations": LIMITATIONS,
    }
    return {"data": data, "meta": meta}
