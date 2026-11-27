"""从本地简历库生成投递用 PDF（中文）。

设计：一份用户级简历（L0 基本信息 + L2 经历），存在 RUNTIME_DIR/resumes/，
投递时按任务引用（delivery_tasks.resume_path）。生成失败回退纯文本，绝不因
PDF 库缺失而阻断投递流程。
"""
import json
from pathlib import Path

import config
import db


def build_user_resume(user_id):
    """读取该用户的 L0/L2 生成简历 PDF，返回文件路径（str）。

    PDF 生成失败时回退写 .txt（同样可用于邮件附件/表单上传）。
    """
    conn = db.get_conn()
    row = conn.execute("SELECT l0 FROM user_records WHERE user_id=?", (user_id,)).fetchone()
    l0 = json.loads(row["l0"]) if row and row["l0"] else {}
    rows = conn.execute(
        "SELECT fields FROM experience_items WHERE user_id=? ORDER BY exp_index", (user_id,)
    ).fetchall()
    conn.close()
    l2 = [json.loads(r["fields"]) for r in rows]

    out_dir = Path(config.RUNTIME_DIR) / "resumes"
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / ("resume_u%s.pdf" % user_id)
    txt_path = out_dir / ("resume_u%s.txt" % user_id)

    lines = _plain_lines(l0, l2)
    try:
        _build_pdf(pdf_path, l0, l2)
        return str(pdf_path)
    except Exception:
        # 回退：纯文本简历（仍可作为附件/上传）
        txt_path.write_text("\n".join(lines), encoding="utf-8")
        return str(txt_path)


def _plain_lines(l0, l2):
    lines = [str(l0.get("姓名", "")), ""]
    for k in ("手机", "邮箱", "学校", "专业", "学历阶段", "意向岗位"):
        if l0.get(k):
            lines.append("%s：%s" % (k, l0.get(k)))
    skills = l0.get("技能")
    if skills:
        lines.append("技能：%s" % ("、".join(skills) if isinstance(skills, list) else skills))
    lines.append("")
    for e in l2 or []:
        head = "%s｜%s｜%s" % (e.get("类型", ""), e.get("名称", ""), e.get("角色", ""))
        t = "%s ~ %s" % (e.get("时间起", ""), e.get("时间止", ""))
        lines.append("■ %s（%s）" % (head, t))
        if e.get("事项"):
            lines.append("  " + str(e["事项"]))
        if e.get("结果"):
            lines.append("  成果：" + str(e["结果"]))
        if e.get("技术工具"):
            lines.append("  技术工具：" + str(e["技术工具"]))
        lines.append("")
    return lines


def _build_pdf(pdf_path, l0, l2):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.colors import HexColor
    from xml.sax.saxutils import escape

    cn = "STSong-Light"  # reportlab 内置 CJK 字体，无需系统字体文件
    if cn not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(UnicodeCIDFont(cn))

    def para(value, style):
        return Paragraph(escape(str(value or "")).replace("\n", "<br/>"), style)

    doc = SimpleDocTemplate(str(pdf_path), pagesize=A4,
                            topMargin=20 * mm, bottomMargin=20 * mm,
                            leftMargin=20 * mm, rightMargin=20 * mm)
    ss = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=ss["Title"], fontName=cn, fontSize=20,
                           alignment=TA_CENTER, textColor=HexColor("#1a1a1a"))
    sub = ParagraphStyle("s", parent=ss["Normal"], fontName=cn, fontSize=11,
                         alignment=TA_CENTER, textColor=HexColor("#555555"))
    h = ParagraphStyle("h", parent=ss["Heading2"], fontName=cn, fontSize=13,
                       textColor=HexColor("#2c3e50"), spaceBefore=10)
    body = ParagraphStyle("b", parent=ss["Normal"], fontName=cn, fontSize=11,
                          leading=18, wordWrap="CJK", splitLongWords=True)

    story = [para(l0.get("姓名", ""), title)]
    contact = " ｜ ".join(x for x in [
        l0.get("手机", ""), l0.get("邮箱", ""),
        "%s %s" % (l0.get("学校", ""), l0.get("专业", ""))] if x)
    story.append(para(contact, sub))
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", thickness=1, color=HexColor("#cccccc")))

    basics = [(k, l0.get(k)) for k in
              ("性别", "出生日期", "学历阶段", "现居", "意向岗位") if l0.get(k)]
    if basics:
        story.append(Paragraph("基本信息", h))
        story.append(para("　".join("%s：%s" % kv for kv in basics), body))
    skills = l0.get("技能")
    if skills:
        story.append(Paragraph("技能", h))
        story.append(para("、".join(skills) if isinstance(skills, list) else str(skills), body))
    if l2:
        story.append(Paragraph("经历", h))
        for e in l2:
            head = "■ %s｜%s" % (e.get("名称", ""), e.get("角色", ""))
            t = "%s ~ %s" % (e.get("时间起", ""), e.get("时间止", ""))
            story.append(para("%s　%s" % (head, t), body))
            if e.get("事项"):
                story.append(para(e["事项"], body))
            if e.get("结果"):
                story.append(para("成果：" + str(e["结果"]), body))
            if e.get("技术工具"):
                story.append(para("技术工具：" + str(e["技术工具"]), body))
            story.append(Spacer(1, 4))

    doc.build(story)
