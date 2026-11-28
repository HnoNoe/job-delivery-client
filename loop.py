"""检索编排：在已登录平台检索岗位（requests 接口或 DrissionPage 旁听）。

只负责"查"：检索 → 归一化由 crawler 完成 → 入库由 jobstore 完成。
画像/匹配/建任务/反馈等已随裁剪移除。
"""
import crawler
import platforms
import session
from logging_setup import get_logger

log = get_logger(__name__)


def format_event(event):
    """把一条诊断事件格式化为可直接显示的日志行（原因 + 判定依据 + 脱敏 URL）。"""
    platform_key = event.get("platform") or "?"
    prefix = "[%s] " % platform_key
    lines = [prefix + (event.get("message") or event.get("kind") or "检索诊断")]
    kind = event.get("kind") or ""
    rule = event.get("matched_rule")
    if rule:
        lines.append(prefix + "判断依据：%s（阶段：%s）" % (rule, event.get("stage") or "-"))
    if kind != "ok":  # 成功时只留一行汇总，不刷地址
        if event.get("url_read_error"):
            lines.append(prefix + "当前页面：无法获取（%s）" % event["url_read_error"])
            if event.get("last_observed_url"):
                lines.append(prefix + "最后观测页面：%s" % event["last_observed_url"])
        elif event.get("current_url"):
            lines.append(prefix + "当前页面：%s" % event["current_url"])
        elif event.get("requested_url"):
            lines.append(prefix + "请求页面：%s" % event["requested_url"])
    if event.get("partial"):
        lines.append(prefix + "（部分完成）已保留抓到的 %d 条岗位" % event.get("result_count", 0))
    if kind == "blocked_verification" and event.get("surfaced"):
        lines.append(prefix + "验证页面已显示到桌面：完成验证后重新发起检索（GUI 可点「验证后继续检索」）。")
    elif kind in ("blocked_verification", "rate_limited"):
        lines.append(prefix + "请到「平台登录」页签用原浏览器会话人工处理后再发起检索。")
    elif kind == "login_expired":
        lines.append(prefix + "请到「平台登录」页签重新扫码登录。")
    return lines


def _plain_reason(reason):
    """去掉诊断消息里的“抓取到 N 个岗位：”框架，供“检索到 0 个岗位：…”拼接使用。"""
    text = str(reason or "")
    for prefix in ("抓取到 0 个岗位：", "抓取到 0 个岗位:"):
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


def search_logged_in_platforms(platform_keys, keyword, city="", pages=1, on_event=None):
    """在已登录平台检索。真实平台用 DrissionPage 旁听接口（会自己用持久化 profile 重开浏览器）。

    on_event 可选：实时收到格式化后的诊断行（字符串）；不传时行为与旧版一致。
    """
    jobs, logs = [], []

    def emit(line):
        if on_event is None:
            return
        try:
            on_event(line)
        except Exception:
            pass

    for k in platform_keys or []:
        p = platforms.get(k)
        if not p:
            logs.append((k, "未知平台"))
            emit("[%s] 未知平台，已跳过" % k)
            continue
        if not session.can_search(k):
            logs.append((k, "没有可用登录态，跳过"))
            emit("[%s] 没有可用登录态，已跳过：请先到「平台登录」页签完成登录" % k)
            continue

        def relay(event, _emit=emit):
            for line in format_event(event):
                _emit(line)

        try:
            if k == "mock":
                got = crawler.search_via_requests(k, keyword, city=city, pages=pages)
            else:
                got = session.dpage_search(k, keyword, city=city, pages=pages, on_event=relay)
        except Exception as exc:
            logs.append((k, "检索失败：%s" % exc))
            emit("[%s] 检索失败：%s" % (k, exc))
            continue
        jobs.extend(got)
        diag = session.last_search_diagnostic(k)
        if got:
            logs.append((k, "检索到 %d 个岗位" % len(got)))
            if diag.get("partial"):
                logs.append((k, "注意：%s" % (diag.get("message") or "后续抓取已停止")))
            if on_event is not None and k == "mock":
                emit("[%s] 检索到 %d 个岗位" % (k, len(got)))
        else:
            reason = _plain_reason(session.last_search_error(k))
            logs.append((k, "检索到 0 个岗位：%s" % (reason or "登录态可能失效，请重新登录该平台")))
            if on_event is None:
                emit("[%s] 检索到 0 个岗位：%s" % (k, reason or "原因不确定"))
            elif k == "mock":
                emit("[%s] 检索到 0 个岗位：%s" % (k, reason or "接口未返回岗位"))
    return jobs, logs
