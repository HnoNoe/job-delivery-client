# -*- coding: utf-8 -*-
"""
risk.py —— 风控熔断
====================
BOSS 触发风控时有三类可观测特征（2026-11-26 实测）：

1. 页面被重定向到安全挑战页：
       /web/passport/zp/security.html?seed=...&code=36|37&callbackUrl=...
2. 业务接口直接返回：
       {"code":37,"message":"您的环境存在异常."}
3. code 语义：
       36 = 账号异常（可能升级为图形验证码）
       37 = 环境异常（IP / 设备指纹被标记）

命中后的正确做法是【立刻停手】——继续请求只会加长冷却时间，甚至把号打封。
所以这里不重试、不降速重试、不换 UA 重试，只抛异常让调用方停任务。
"""

RISK_URL_MARKS = ("security.html", "/web/passport/zp/security")
CODE_MEANINGS = {
    36: "账号异常（可能被要求图形验证码）",
    37: "环境异常（IP / 设备指纹被标记）",
}


class RiskControlError(RuntimeError):
    """命中风控：调用方应立即停止任务，不要重试。"""

    def __init__(self, reason, url="", code=None):
        self.reason = reason
        self.url = url
        self.code = code
        super().__init__(reason)


def check_url(url):
    """URL 含安全挑战页特征时抛 RiskControlError。"""
    text = str(url or "")
    for mark in RISK_URL_MARKS:
        if mark in text:
            code = None
            if "code=36" in text:
                code = 36
            elif "code=37" in text:
                code = 37
            raise RiskControlError(
                "页面被跳到安全验证页（%s）" % (CODE_MEANINGS.get(code) or "风控挑战"),
                url=text, code=code)
    return True


def check_payload(payload):
    """接口响应 code 非 0（尤其 36/37）时抛 RiskControlError。返回解析后的 dict。"""
    import json

    data = payload
    if isinstance(data, (bytes, bytearray)):
        data = data.decode("utf-8", "replace")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:  # noqa: BLE001
            return {}
    data = data or {}
    code = data.get("code")
    if code in (36, 37):
        raise RiskControlError(
            "接口返回 code=%s：%s" % (code, CODE_MEANINGS.get(code, data.get("message", ""))),
            code=code)
    if code not in (0, None):
        message = data.get("message") or ""
        raise RiskControlError("接口返回 code=%s：%s" % (code, message), code=code)
    return data


def advice():
    """命中风控后的处理建议（打印给用户看）。"""
    return ("建议：立刻停手，冷却 30–60 分钟再试；期间不要刷新、不要换关键词继续抓。"
            "若反复出现，检查是否用了代理/云服务器 IP，或登录态是否已失效。")
