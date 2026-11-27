"""规则引擎回归：切分、类型、日期精度、证书/荣誉、空值语义。全部使用合成数据。"""
import resume_rules
import resume_ai
import schema

SAMPLE = """张小明
教育经历
2022.9-2026.6 某某大学
学业成绩：平均分 88.5，专业排名 3/120
在校经历
2022.9-至今：2022 级 1 班学习委员
负责课程通知与作业汇总，班级获评校级先进班集体。
2023.3-2024.6：院学生会干事→部长
组织迎新晚会，服务 500 名学生。
工作
2025.7-2025.8：某科技公司实习
参与数据清洗与报表整理。
科研&实践经历
2025.9-2026.1：某某创新项目负责人
带队完成原型开发，获评校级优秀团队。
相关技能
熟练使用 Python、Excel 与剪映。
荣誉证书
证书：计算机二级、大学英语 4 级【500】
校/院级：优秀共青团员、社会实践先进个人
生日：2003.05 手机：13800000000 邮箱：demo@example.com
求职意向：数据分析
"""


def test_l0_fields_from_labels_not_polluted():
    data = resume_rules.parse(SAMPLE)["data"]
    assert data["姓名"] == "张小明"
    assert data["学校"] == "某某大学"
    assert data["入学年月"] == "2022-09"
    assert data["毕业年月"] == "2026-06"
    assert data["手机"] == "13800000000"
    assert data["邮箱"] == "demo@example.com"
    assert data["出生日期"] == "2003-05"
    assert data["意向岗位"] == "数据分析"
    # 关键回归：不得把「专业排名」当成「专业」
    assert "专业" not in data


def test_experience_split_types_and_roles():
    rows = resume_rules.parse(SAMPLE)["data"]["经历"]
    types = [r["类型"] for r in rows]
    assert types == ["学生工作", "学生工作", "实习/工作", "项目", "证书", "证书"]
    assert rows[0]["名称"] == "2022 级 1 班" and rows[0]["角色"] == "学习委员"
    assert rows[1]["角色"] == "干事→部长"
    assert rows[3]["名称"] == "某某创新项目" and rows[3]["角色"] == "负责人"
    # 结果只在有依据时拆出，且不搬走正文
    assert "校级优秀团队" in rows[3]["结果"]
    assert "校级优秀团队" in rows[3]["事项"]
    # 证书：一条标签行拆成独立条目，成绩保留原文、不改写评分
    assert rows[4]["名称"] == "计算机二级"
    assert rows[5]["名称"] == "大学英语 4 级"
    assert "500" in rows[5]["结果"]


def test_honors_go_to_unmapped_not_fabricated():
    meta = resume_rules.parse(SAMPLE)["meta"]
    texts = [u["text"] for u in meta["unmapped_content"]]
    assert texts == ["优秀共青团员", "社会实践先进个人"]
    assert all(u["reason"] for u in meta["unmapped_content"])


def test_date_precision_and_invalid_month():
    text = """李四
在校经历
2024 某某社团成员
参与社团日常运营。
2025.13-2026.1：非法月份项目
内容略。
2026.8：单月实习
内容略。
"""
    res = resume_rules.parse(text)
    rows = res["data"]["经历"]
    assert rows[0]["时间起"] == "2024"          # 只有年份，不补造月份
    assert rows[0]["时间止"] == ""
    assert rows[1]["时间起"] == "2025.13"        # 非法月保留原文
    assert any("非法月份" in w["message"] for w in res["meta"]["warnings"])
    assert rows[2]["时间起"] == "2026-08" and rows[2]["时间止"] == ""


def test_normalize_skills_strips_phrases_and_duplicates():
    s = ("熟练使用 WPS、Excel 数据统计；掌握剪映，具备图文、视频制作能力。"
         "熟练使用豆包、通义千问、ChatGPT 等 AI 工具，进行资料搜集整理、文案润色、"
         "PPT 大纲搭建、辅助数据分析等。")
    got = resume_rules.normalize_skills([s])
    assert got == ["WPS", "剪映", "豆包", "通义千问", "ChatGPT", "文案润色"]
    assert len({x.lower() for x in got}) == len(got)          # 无重复
    assert not any("熟练" in x or "具备" in x for x in got)   # 无动词短语
    warns = []
    resume_rules.normalize_skills(["具备图文"], warns)
    assert warns and "丢弃" in warns[0]["message"]           # 碎片有告警，不静默


def test_type_normalization_rules():
    assert resume_ai._norm_type("实习") == "实习/工作"
    assert resume_ai._norm_type("工作") == "实习/工作"
    assert resume_ai._norm_type("科研") == "项目"
    assert resume_ai._norm_type("科研工作", title="某论文发表") == "论文"
    assert resume_ai._norm_type("") == ""                      # 未知不默认成项目
    assert resume_ai._norm_type("", section="项目") == "项目"   # 章节兜底


def test_none_is_empty_not_literal_none():
    assert resume_ai._cap(None) == ""
    assert resume_ai._cap(" x ") == "x"
    row = resume_ai._clean_experience([{"类型": "实习", "名称": "A", "挂靠": None}], [])[0]
    assert "None" not in str(row)
    assert all(v is not None for v in row.values())


def test_long_text_is_chunked_not_silently_truncated():
    body = "\n".join("经历段落 %03d 描述内容" % i for i in range(400))
    chunks = resume_ai._split_chunks(body, size=2000)
    assert len(chunks) > 1
    assert "\n".join(chunks) == body           # 不丢尾部
