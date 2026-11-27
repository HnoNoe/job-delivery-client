"""简历存取：本地客户端版。

与 FastAPI 版（v1 mydata.py）同一套解析/存储逻辑，搬到本地：
- L0 字段 + 意向岗位 + 经历列表（L2），按账号（owner）隔离；
- 与 8445 网页版数据同构：user_records(l0/l1/l3) + experience_items；
- 无画像/匹配，经历不计算向量（embedding 列留空）。
"""
import json
import re

import db


def ensure_user_id(owner):
    """当前账号对应的 user_records 行，不存在则创建。返回 user_id。"""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT user_id FROM user_records WHERE owner = ? ORDER BY user_id LIMIT 1",
        (owner,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO user_records (l0, l1, l3, owner) VALUES ('{}', '{}', '{}', ?)",
            (owner,))
        conn.commit()
        row = conn.execute(
            "SELECT user_id FROM user_records WHERE owner = ? ORDER BY user_id LIMIT 1",
            (owner,)).fetchone()
    conn.close()
    return row[0]


def load_resume(owner):
    """读取我的简历：L0 字段 + 意向岗位 + 经历明细。无记录返回 None。"""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT user_id, l0, l1, l3 FROM user_records WHERE owner = ? ORDER BY user_id LIMIT 1",
        (owner,)).fetchone()
    if row is None:
        conn.close()
        return None
    uid = row["user_id"] if isinstance(row, dict) else row[0]
    l0 = json.loads((row["l0"] if isinstance(row, dict) else row[1]) or "{}")
    l3 = json.loads((row["l3"] if isinstance(row, dict) else row[3]) or "{}")
    exps = []
    for r in conn.execute(
            "SELECT fields FROM experience_items WHERE user_id = ? ORDER BY exp_index", (uid,)):
        f = r["fields"] if isinstance(r, dict) else r[0]
        exps.append(json.loads(f or "{}"))
    conn.close()
    skills = [s for s in str(l0.get("技能", "")).split("、") if s.strip()]
    return {"user_id": uid, "l0": l0, "意向岗位": l3.get("意向岗位", ""),
            "技能": skills, "experiences": exps}


def save_resume(owner, parsed):
    """保存/覆盖我的简历。parsed: {L0字段…, '意向岗位': str, '经历': [{类型,名称,…}]}"""
    l0 = {k: str(v) for k, v in parsed.items()
          if k not in ("技能", "经历", "意向岗位") and v is not None}
    # 技能：schema 没有独立列，按 l0 的附属键存顿号串，读取时还原成列表
    skills = parsed.get("技能") or []
    if isinstance(skills, str):
        skills = [s for s in re.split(r"[、,，;；]+", skills) if s.strip()]
    skills = [str(s).strip() for s in skills if str(s).strip()]
    if skills:
        l0["技能"] = "、".join(skills)
    l1 = {}
    for e in parsed.get("经历", []) or []:
        if isinstance(e, dict) and e.get("类型"):
            l1[e["类型"]] = l1.get(e["类型"], 0) + 1
    l3 = {"意向岗位": parsed.get("意向岗位", "")}
    uid = ensure_user_id(owner)
    conn = db.get_conn()
    conn.execute(
        "UPDATE user_records SET l0 = ?, l1 = ?, l3 = ? WHERE user_id = ?",
        (json.dumps(l0, ensure_ascii=False), json.dumps(l1, ensure_ascii=False),
         json.dumps(l3, ensure_ascii=False), uid))
    conn.execute("DELETE FROM experience_items WHERE user_id = ?", (uid,))
    for i, e in enumerate(parsed.get("经历", []) or []):
        if not isinstance(e, dict):
            continue
        conn.execute(
            "INSERT INTO experience_items (user_id, exp_index, fields) VALUES (?, ?, ?)",
            (uid, i, json.dumps(e, ensure_ascii=False)))
    conn.commit()
    conn.close()
    return uid
