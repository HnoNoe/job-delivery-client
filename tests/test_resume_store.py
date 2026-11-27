"""存储回归：L2/L1 回读一致，解析元数据不得污染 L0。全部使用临时 SQLite。"""
import json

import config
import db
import resume_ai
import resume_store


def test_skills_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "s.db"), raising=False)
    db.init_db()
    parsed = resume_ai.smart_parse_ex(TEXT, "rule")["data"]
    parsed["技能"] = ["Excel", "WPS", "剪映"]
    resume_store.save_resume("skill_user", parsed)
    loaded = resume_store.load_resume("skill_user")
    assert loaded["技能"] == ["Excel", "WPS", "剪映"]
    # 技能以顿号串存 l0 附属键，不能污染 L0 标准字段
    assert loaded["l0"].get("技能") == "Excel、WPS、剪映"
    assert "经历" not in loaded["l0"]

TEXT = """赵六
在校经历
2024.9-2025.1：某班班长
组织班级活动。
证书：普通话二级甲等
手机：13700000000
"""


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"), raising=False)
    db.init_db()
    parsed = resume_ai.smart_parse_ex(TEXT, "rule")["data"]
    uid = resume_store.save_resume("tester", parsed)
    assert uid

    loaded = resume_store.load_resume("tester")
    assert len(loaded["experiences"]) == len(parsed["经历"]) == 2
    assert [e["名称"] for e in loaded["experiences"]] == [r["名称"] for r in parsed["经历"]]
    # 元数据不得进入 L0
    l0 = loaded["l0"]
    assert "meta" not in l0 and "经历" not in l0 and "智能" not in l0
    assert l0.get("姓名") == "赵六"

    # L1 分类计数与经历条数一致
    conn = db.get_conn()
    row = conn.execute("SELECT l1 FROM user_records WHERE owner = 'tester'").fetchone()
    conn.close()
    l1 = json.loads(row["l1"] if isinstance(row, dict) else row[0])
    assert sum(l1.values()) == 2
