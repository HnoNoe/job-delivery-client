"""BOSS 直聘响应解析：joblist / job detail / 会话列表 -> 统一字段。

字段口径来自实测（2026-11-26）：
- 列表接口 zpData.jobList[]：jobName / salaryDesc / cityName / jobExperience / jobDegree ...
- 详情接口 zpData：atsOnlineApplyInfo / oneKeyResumeInfo / relationInfo（BOSS 没有 entryType/entryAddr）
- 会话接口 zpData.result[]：name / brandName / jobName / lastMsg / lastTS / encryptFriendId
"""
import json

# 列表字段 -> 统一字段（与 schema.JOB_FIELDS 对齐）
_JOBLIST_MAP = {
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


def _load(payload):
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", "replace")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except Exception:  # noqa: BLE001
            return {}
    return payload or {}


def _job_link(encrypt_id):
    return "/job_detail/%s.html" % encrypt_id if encrypt_id else ""


def parse_joblist(payload):
    """职位列表响应 -> 统一岗位字段列表。"""
    data = _load(payload)
    if data.get("code") not in (0, None):
        return []
    rows = []
    for raw in ((data.get("zpData") or {}).get("jobList") or []):
        item = {}
        for src, dst in _JOBLIST_MAP.items():
            value = raw.get(src)
            if value:
                item[dst] = value
        encrypt_id = raw.get("encryptJobId") or ""
        if encrypt_id:
            item["岗位链接"] = _job_link(encrypt_id)
            item["平台岗位ID"] = encrypt_id
        if raw.get("encryptBrandId"):
            item["公司ID"] = raw["encryptBrandId"]
        skills = raw.get("skills") or []
        if skills:
            item["技能"] = ",".join(skills)
        if raw.get("contact"):
            item["已沟通"] = "是"
        if item.get("岗位名称") and item.get("单位名称"):
            rows.append(item)
    return rows


def parse_detail(payload):
    """职位详情响应 -> 投递判定（五布尔 + 职位信息）。"""
    data = _load(payload)
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
        "城市": job.get("locationName", ""),
        "经验": job.get("experienceName", ""),
        "学历": job.get("degreeName", ""),
        "职位码": job.get("position"),
        "已投递": bool(ats.get("alreadyApply")),
        "可一键投简历": bool(one_key.get("canSendResume")),
        "可发手机": bool(one_key.get("canSendPhone")),
        "可发微信": bool(one_key.get("canSendWechat")),
        "已开聊": bool(relation.get("beFriend")),
        "已感兴趣": bool(relation.get("interestJob")),
        "职位有效": not bool(job.get("invalidStatus")),
    }


def decide_entry(detail):
    """投递判定 -> (入口类型, 说明)；入口类型对齐 schema.ENTRY_TYPES。"""
    if not detail:
        return "半自动", "详情未取到，按半自动处理"
    if detail.get("已投递"):
        return "API", "该岗位已投递，跳过"
    if detail.get("可一键投简历"):
        return "Web表单", "可一键发送附件简历"
    if detail.get("已开聊"):
        return "半自动", "已在沟通中"
    return "半自动", "点「立即沟通」发招呼语"


def parse_friend_list(payload):
    """会话列表响应（zprelation/friend/*） -> 会话行。"""
    data = _load(payload)
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


# 详情页 DOM 状态读取（详情接口在 SEO 页不触发，改为读按钮文案）
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


def read_entry_state(raw):
    """把 ENTRY_STATE_JS 的返回值转成 dict。"""
    data = _load(raw)
    return data if isinstance(data, dict) else {}


def decide_entry_state(state):
    """按页面按钮文案判定投递入口 -> (入口类型, 说明)。"""
    label = (state or {}).get("label") or ""
    if "继续沟通" in label:
        return "半自动", "已开聊，跳过"
    if "立即沟通" in label:
        return "半自动", "点「立即沟通」发招呼语"
    if (state or {}).get("hasSent"):
        return "API", "页面显示已投递，跳过"
    if (state or {}).get("hasResume"):
        return "Web表单", "页面出现「投递简历/上传附件简历」入口"
    return "未知", "未找到投递入口按钮"


# 登录态 DOM 判据（不发额外请求）：已登录时顶栏出现「消息/简历 + 用户名」，未登录是「登录/注册」
LOGIN_STATE_JS = (
    "(function(){"
    "var nav=document.querySelector('.user-nav');"
    "var txt=nav?nav.innerText:'';"
    "var el=document.querySelector('.nav-figure,[class*=nav-figure]');"
    "var name=el?(el.innerText||'').trim():'';"
    "var logged=txt.indexOf('消息')>=0&&txt.indexOf('登录/注册')<0;"
    "return JSON.stringify({loggedIn:logged,name:name,navText:(txt||'').slice(0,40),url:location.href});"
    "})()"
)


def parse_login_state(raw):
    """把 LOGIN_STATE_JS 的返回值转成 dict。"""
    data = _load(raw)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# 风控判定（实测 2026-11-26）：页面跳安全挑战页 / 接口 code=36|37
# ---------------------------------------------------------------------------
RISK_URL_MARKS = ("security.html", "/web/passport/zp/security")
RISK_CODES = {36: "账号异常（可能被要求图形验证码）", 37: "环境异常（IP / 设备指纹被标记）"}
RISK_ADVICE = ("建议：立刻停手，冷却 30–60 分钟再试；期间不要刷新、不要继续抓。"
               "反复出现请检查是否用了代理/云 IP，或登录态是否失效。")


def detect_risk(url=None, payload=None):
    """命中风控返回说明字符串，否则返回空串。"""
    text = str(url or "")
    for mark in RISK_URL_MARKS:
        if mark in text:
            code = 36 if "code=36" in text else (37 if "code=37" in text else None)
            return "页面被跳到安全验证页（%s）" % (RISK_CODES.get(code) or "风控挑战")
    if payload:
        data = _load(payload)
        code = data.get("code")
        if code in RISK_CODES:
            return "接口返回 code=%s：%s" % (code, RISK_CODES[code])
        if code not in (0, None):
            return "接口返回 code=%s：%s" % (code, data.get("message") or "")
    return ""
