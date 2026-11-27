# -*- coding: utf-8 -*-
"""
parser.py —— 响应解析
======================
把 BOSS 的接口响应和页面状态解析成统一字段。

字段口径来自 2026-11-26 实测：
    列表  /wapi/zpgeek/search/joblist.json   -> zpData.jobList[]
    详情  /wapi/zpgeek/job/detail.json       -> zpData.atsOnlineApplyInfo / oneKeyResumeInfo / relationInfo
    会话  /wapi/zprelation/friend/*          -> zpData.result[] / friendList[]
"""

import json

# 列表字段 -> 中文列名
JOBLIST_MAP = {
    "jobName": "岗位名称",
    "brandName": "单位名称",
    "cityName": "城市",
    "areaDistrict": "区域",
    "businessDistrict": "商圈",
    "jobExperience": "经验",
    "jobDegree": "学历",
    "brandIndustry": "行业",
    "brandScaleName": "公司规模",
    "brandStageName": "融资阶段",
    "bossName": "HR",
    "bossTitle": "HR职位",
}

COLUMNS = ["岗位名称", "单位名称", "薪资", "城市", "区域", "经验", "学历",
           "行业", "公司规模", "HR", "HR职位", "技能", "岗位链接"]


def loads(payload):
    """bytes/str -> dict（解析失败返回空 dict）。"""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return {}
    return payload or {}


def parse_joblist(payload):
    """职位列表响应 -> 岗位行列表。"""
    data = loads(payload)
    if data.get("code") not in (0, None):
        return []
    rows = []
    for raw in ((data.get("zpData") or {}).get("jobList") or []):
        item = {}
        for src, dst in JOBLIST_MAP.items():
            value = raw.get(src)
            if value:
                item[dst] = value
        if raw.get("salaryDesc"):
            item["薪资"] = raw["salaryDesc"]
        skills = raw.get("skills") or []
        if skills:
            item["技能"] = ",".join(skills)
        encrypt_id = raw.get("encryptJobId") or ""
        if encrypt_id:
            item["岗位链接"] = "/job_detail/%s.html" % encrypt_id
            item["岗位ID"] = encrypt_id
        if item.get("岗位名称") and item.get("单位名称"):
            rows.append(item)
    return rows


def parse_detail(payload):
    """职位详情响应 -> 投递相关的布尔状态。"""
    data = loads(payload)
    if data.get("code") not in (0, None):
        return {}
    zp = data.get("zpData") or {}
    job = zp.get("jobInfo") or {}
    ats = zp.get("atsOnlineApplyInfo") or {}
    one_key = zp.get("oneKeyResumeInfo") or {}
    relation = zp.get("relationInfo") or {}
    return {
        "岗位名称": job.get("jobName", ""),
        "薪资": job.get("salaryDesc", ""),
        "已投递": bool(ats.get("alreadyApply")),
        "可一键投简历": bool(one_key.get("canSendResume")),
        "可发手机": bool(one_key.get("canSendPhone")),
        "已开聊": bool(relation.get("beFriend")),
        "职位有效": not bool(job.get("invalidStatus")),
    }


def parse_friend_list(payload):
    """会话列表响应 -> 会话行。"""
    data = loads(payload)
    if data.get("code") not in (0, None):
        return []
    zp = data.get("zpData") or {}
    rows = []
    for raw in (zp.get("result") or zp.get("friendList") or []):
        row = {
            "HR": raw.get("name") or raw.get("friendName") or "",
            "单位名称": raw.get("brandName", ""),
            "岗位名称": raw.get("jobName", ""),
            "城市": raw.get("jobCity", ""),
            "HR职位": raw.get("bossTitle", ""),
            "最后消息": raw.get("lastMsg") or ((raw.get("lastMessageInfo") or {}).get("text") or ""),
            "最后时间": raw.get("lastTime", ""),
            "会话ID": raw.get("encryptFriendId") or raw.get("encryptUid") or "",
        }
        if row["HR"] or row["岗位名称"]:
            rows.append(row)
    return rows


# 详情页 DOM：投递入口按钮文案（SEO 详情页不请求 detail 接口，只能读页面）
ENTRY_STATE_JS = (
    "(function(){var out={label:'',hasResume:false,hasSent:false,url:location.href};"
    "var bs=document.querySelectorAll('.btn-startchat');"
    "for(var i=0;i<bs.length;i++){var r=bs[i].getBoundingClientRect();if(r.width<10)continue;"
    "out.label=(bs[i].innerText||'').trim();break;}"
    "var body=document.body?document.body.innerText:'';"
    "out.hasResume=body.indexOf('投递简历')>=0||body.indexOf('上传附件简历')>=0;"
    "out.hasSent=body.indexOf('已投递')>=0||body.indexOf('继续沟通')>=0;"
    "return JSON.stringify(out);})()"
)

# 顶栏 DOM：登录态判据（已登录出现「消息/简历」，未登录是「登录/注册」）
LOGIN_STATE_JS = (
    "(function(){"
    "var nav=document.querySelector('.user-nav');"
    "var txt=nav?nav.innerText:'';"
    "var el=document.querySelector('.nav-figure,[class*=nav-figure]');"
    "var name=el?(el.innerText||'').trim():'';"
    "var logged=txt.indexOf('消息')>=0&&txt.indexOf('登录/注册')<0;"
    "return JSON.stringify({loggedIn:logged,name:name,url:location.href});})()"
)


def read_state(raw):
    data = loads(raw)
    return data if isinstance(data, dict) else {}


def decide_entry(detail, state=None):
    """投递入口判定 -> (入口类型, 说明)。"""
    if detail:
        if detail.get("已投递"):
            return "已投递", "该岗位已投递过"
        if detail.get("已开聊"):
            return "已开聊", "已经在沟通中"
        if detail.get("可一键投简历"):
            return "Web表单", "可一键发送附件简历"
    state = state or {}
    label = state.get("label") or ""
    if "继续沟通" in label:
        return "已开聊", "按钮显示「继续沟通」"
    if "立即沟通" in label:
        return "半自动", "点「立即沟通」发招呼语"
    if state.get("hasSent"):
        return "已投递", "页面显示已投递"
    if state.get("hasResume"):
        return "Web表单", "页面有「投递简历」入口"
    return "未知", "没找到投递入口"
