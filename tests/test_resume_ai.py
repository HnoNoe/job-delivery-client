"""AI 引擎与合并层回归：模式语义、失败分类、合并保真。全部离线（不联网）。"""
import json

import pytest

import config
import resume_ai

TEXT = """王五
在校经历
2023.9-至今：某班团支书
组织团日活动，获评优秀团支部。
证书：计算机二级
手机：13900000000
"""


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "", raising=False)


def test_rule_mode_never_calls_model(monkeypatch):
    called = []
    monkeypatch.setattr(resume_ai, "_post_chat", lambda *a, **k: called.append(1))
    res = resume_ai.smart_parse_ex(TEXT, "rule")
    assert called == []
    assert res["meta"]["used_engine"] == "rule"
    assert res["meta"]["ai_status"] == "not_requested"
    assert len(res["data"]["经历"]) == 2


def test_auto_without_key_degrades_and_says_so():
    res = resume_ai.smart_parse_ex(TEXT, "auto")
    assert res["meta"]["ai_status"] == "not_configured"
    assert res["meta"]["used_engine"] == "rule"
    assert any("未配置" in w["message"] for w in res["meta"]["warnings"])
    assert len(res["data"]["经历"]) == 2     # 规则结果照常产出


def test_ai_mode_without_key_marks_not_ai(monkeypatch):
    res = resume_ai.smart_parse_ex(TEXT, "ai")
    assert res["meta"]["ai_status"] == "not_configured"
    assert any("没有调用模型" in w["message"] for w in res["meta"]["warnings"])


def _fake_payload(**kwargs):
    base = {"姓名": "王五", "技能": ["Excel"], "经历": []}
    base.update(kwargs)
    return json.dumps(base, ensure_ascii=False)


def test_hybrid_keeps_rule_rows_ai_omitted(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(resume_ai, "_post_chat",
                        lambda *a, **k: _fake_payload(经历=[
                            {"类型": "学生工作", "名称": "某班", "时间起": "2023.9", "时间止": ""}]))
    res = resume_ai.smart_parse_ex(TEXT, "auto")
    assert res["meta"]["used_engine"] == "hybrid"
    assert res["meta"]["ai_status"] == "success"
    names = [r["名称"] for r in res["data"]["经历"]]
    assert "某班" in names
    # 规则里那条「某班团支书」被 AI 覆盖/合并，证书那条 AI 没提，必须保留
    assert any(r["类型"] == "证书" for r in res["data"]["经历"])
    assert any("未覆盖" in w["message"] for w in res["meta"]["warnings"])


def test_ai_new_row_is_appended_and_flagged(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(resume_ai, "_post_chat",
                        lambda *a, **k: _fake_payload(经历=[
                            {"类型": "项目", "名称": "AI 额外发现的科研项目",
                             "事项": "原文第 9 行"}]))
    res = resume_ai.smart_parse_ex(TEXT, "auto")
    names = [r["名称"] for r in res["data"]["经历"]]
    assert "AI 额外发现的科研项目" in names
    assert any("AI 新增" in w["message"] for w in res["meta"]["warnings"])


def test_ai_invalid_json_keeps_rule_result(monkeypatch):
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(resume_ai, "_post_chat", lambda *a, **k: "not json at all")
    res = resume_ai.smart_parse_ex(TEXT, "auto")
    assert res["meta"]["used_engine"] == "rule"
    assert res["meta"]["ai_status"] == "failed"
    assert len(res["data"]["经历"]) == 2
    assert any("invalid_json" in w["message"] for w in res["meta"]["warnings"])


def test_ai_clean_rejects_non_list_and_non_dict():
    warns = []
    assert resume_ai._clean_experience("oops", warns) == []
    out = resume_ai._clean_experience([None, {"类型": "实习", "名称": "A"}], warns)
    assert len(out) == 1 and warns


def test_signature_and_skill_split_helpers():
    assert resume_ai.split_skills("A、B，C;D") == ["A", "B", "C", "D"]
    assert resume_ai.split_skills("") == []
    assert resume_ai.experience_signature({"类型": "项目", "名称": "A B", "时间起": "2024-01"}) == \
        resume_ai.experience_signature({"类型": " 项目 ", "名称": "AB", "时间起": "2024.01"})
    assert resume_ai.experience_signature({"名称": "A", "时间起": "2024-01"}) != \
        resume_ai.experience_signature({"名称": "A", "时间起": "2024-02"})


def test_match_score_links_ai_row_with_role_in_name():
    rule_row = {"类型": "学生工作", "名称": "应用化学 202303 班",
                "角色": "宣传委员兼文娱委员", "时间起": "2023-09"}
    ai_row = {"类型": "学生工作", "名称": "应用化学202303班宣传委员兼文娱委员",
              "时间起": "2023-09"}
    assert resume_ai.match_score(ai_row, rule_row) >= 8
    unrelated = {"类型": "项目", "名称": "完全不相干的项目名称", "时间起": "2023-09"}
    assert resume_ai.match_score(unrelated, rule_row) == 0


def test_honor_rows_are_filtered_not_turned_into_certs():
    assert resume_ai._looks_like_honor({"名称": "优秀共青团员（校/院级）"}) is True
    assert resume_ai._looks_like_honor({"名称": "社会实践先进个人"}) is True
    assert resume_ai._looks_like_honor({"名称": "大学英语 4 级【489】"}) is False
    assert resume_ai._looks_like_honor({"名称": "计算机二级"}) is False


def test_merge_keeps_rule_rows_and_moves_honors_to_unmapped():
    rule = resume_ai.parse_rule(TEXT)["data"]
    n_rule = len(rule["经历"])
    ai_data = {"经历": [{"类型": "证书", "名称": "优秀共青团员", "事项": "校/院级"}]}
    warns, unmapped = [], []
    merged = resume_ai.merge_rule_and_ai(rule, ai_data, warns, unmapped)
    assert len(merged["经历"]) == n_rule          # 荣誉不新增经历
    assert unmapped and "荣誉" in unmapped[0]["reason"]
    assert any("荣誉类" in w["message"] for w in warns)


def test_legacy_smart_parse_returns_data_only():
    data = resume_ai.smart_parse(TEXT)
    assert isinstance(data, dict) and "经历" in data and "meta" not in data
