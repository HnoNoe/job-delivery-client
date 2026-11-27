"""简历识别（规则 + DeepSeek AI 双引擎）—— 本地/云端共用同一份。

本文件是"同一个物体"：本地客户端直接 import；云端服务端（/opt/jobweb）部署的也是本文件。
智能解析入口 smart_parse(text)：AI 抽取为准、规则补空，输出与简历保存链路同构的
{L0字段…, '意向岗位': str, '技能': [..], '经历': [{类型,名称,…}]}。
不依赖任何业务模块（无 recommend/embedding），可独立测试。
"""
import json
import re
import urllib.request

import config
import schema

_L1 = set(schema.L1_TYPES)

# ---------- 规则引擎（补空用） ----------
_SKILL_BANK = ["Python", "Java", "C++", "Go", "JavaScript", "TypeScript", "Vue", "React",
               "MySQL", "Redis", "MongoDB", "Linux", "Docker", "Kubernetes", "Git",
               "Spring", "SpringBoot", "Django", "Flask", "FastAPI", "Node.js",
               "机器学习", "深度学习", "NLP", "CV", "数据分析", "Excel", "SQL",
               "Photoshop", "AutoCAD", "SolidWorks", "Matlab", "SPSS",
               "英语", "CET-4", "CET-6", "普通话"]


def _rule_parse(text):
    """规则抽取：手机/邮箱/姓名/学校/专业/技能。经历不做规则抽取（交给 AI）。"""
    out = {}
    t = text or ""
    m = re.search(r"1[3-9]\d{9}", t)
    if m:
        out["手机"] = m.group(0)
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", t)
    if m:
        out["邮箱"] = m.group(0)
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    if lines and len(lines[0]) <= 20 and not re.search(r"\d{3,}", lines[0]):
        cand = re.sub(r"[（(].*?[)）]", "", lines[0]).strip()
        if 2 <= len(cand) <= 6:
            out.setdefault("姓名", cand)
    m = re.search(r"([一-龥]{2,12}(?:大学|学院|职业技术学院|高等专科学校))", t)
    if m:
        out["学校"] = m.group(1)
    m = re.search(r"(?:专业|所学专业)[:：\s]*([一-龥a-zA-Z]{2,20})(?=[\s，,。/]|$)", t)
    if m:
        out["专业"] = m.group(1)
    hits = [s for s in _SKILL_BANK if s.lower() in t.lower()]
    if hits:
        out["技能"] = hits
    return out


# ---------- AI 引擎（DeepSeek，OpenAI 兼容接口） ----------
_SYSTEM = (
    "你是简历信息抽取器。只能从给定简历原文中提取信息，不得编造、不得推测；"
    "原文没有的字段一律省略或填空字符串。严格只输出 JSON 对象，不要输出任何其他文字。"
)


def _cap(s, n=200):
    return str(s)[:n]


def _norm_date(s):
    s = str(s or "")
    m = re.search(r"(20\d{2})\s*[年./-]\s*(\d{1,2})", s)
    if m:
        return "%s-%02d" % (m.group(1), int(m.group(2)))
    m = re.search(r"(20\d{2})", s)
    return "%s-01" % m.group(1) if m else s


def _norm_type(s):
    s = str(s or "")
    for t in schema.L1_TYPES:
        if t in s:
            return t
    return "项目" if s else ""


def _clean_experience(items):
    out = []
    for e in items if isinstance(items, list) else []:
        if not isinstance(e, dict):
            continue
        row = {k: _cap(e.get(k, ""), 200) for k in schema.L2_FIELDS}
        row["类型"] = _norm_type(row["类型"])
        row["时间起"] = _norm_date(row["时间起"])
        row["时间止"] = _norm_date(row["时间止"])
        if row["名称"] or row["事项"]:
            out.append(row)
    return out[:20]


def _build_prompt(text):
    return (
        "从以下简历原文抽取字段，输出 JSON：\n"
        "{姓名, 性别, 出生日期, 学校, 学院, 专业, 学历阶段, 手机, 邮箱, 意向岗位, 技能: [..], "
        "经历: [{类型(实习/工作|项目|竞赛|论文|专利|学生工作|证书|作品链接), 名称, 角色, "
        "时间起, 时间止, 事项, 结果, 技术工具}]}\n\n" + text[:6000]
    )


def _post_chat(prompt, system, timeout=45):
    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("未配置 DeepSeek API Key")
    body = json.dumps({
        "model": config.DEEPSEEK_MODEL,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        config.DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + config.DEEPSEEK_API_KEY})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"]["content"]


def parse_with_ai(text):
    """DeepSeek 抽取 → 白名单核对后的字段字典；任何失败返回 {}。"""
    if not text or not config.DEEPSEEK_API_KEY:
        return {}
    try:
        raw = _post_chat(_build_prompt(text), _SYSTEM)
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        return {}
    out = {}
    for k in schema.L0_FIELDS:
        v = data.get(k)
        if isinstance(v, (str, int, float)):
            v = _cap(v, 50)
            if v:
                out[k] = v
    v = data.get("意向岗位")
    if isinstance(v, (str, int, float)) and _cap(v, 30):
        out["意向岗位"] = _cap(v, 30)
    skills = data.get("技能")
    if isinstance(skills, list):
        out["技能"] = [_cap(s, 20) for s in skills if _cap(s, 20)][:30]
    exps = _clean_experience(data.get("经历"))
    if exps:
        out["经历"] = exps
    return out


def smart_parse(text):
    """规则 + AI 混合解析：AI 抽取为准、规则补空，技能取并集，经历 AI 优先。"""
    rule = _rule_parse(text)
    try:
        ai = parse_with_ai(text)
    except Exception:
        ai = {}
    merged = dict(rule)
    for k, v in ai.items():
        if k in ("技能", "经历"):
            continue
        if v:
            merged[k] = v
    if ai.get("技能"):
        merged["技能"] = sorted(set(rule.get("技能", [])) | set(ai["技能"]))
    if ai.get("经历"):
        merged["经历"] = ai["经历"]
    return merged


# ---------- 文件文本提取 ----------
def extract_text(path):
    """从简历文件提取纯文本。支持 txt/md/pdf/docx；缺库时给出明确提示。"""
    lower = str(path).lower()
    if lower.endswith((".txt", ".md")):
        for enc in ("utf-8", "gbk"):
            try:
                return open(path, encoding=enc).read()
            except UnicodeDecodeError:
                continue
        return open(path, encoding="utf-8", errors="replace").read()
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("读 PDF 需要 pypdf：pip install pypdf")
        return "\n".join((p.extract_text() or "") for p in PdfReader(path).pages)
    if lower.endswith(".docx"):
        try:
            import docx
        except ImportError:
            raise RuntimeError("读 DOCX 需要 python-docx：pip install python-docx")
        d = docx.Document(path)
        return "\n".join(p.text for p in d.paragraphs)
    raise RuntimeError("不支持的文件类型（支持 txt/md/pdf/docx）")
