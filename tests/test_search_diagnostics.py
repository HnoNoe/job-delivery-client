"""检索诊断与随机滚动间隔的针对性测试（不需要真实浏览器、不访问真实平台）。

运行：python -m pytest tests -q
"""
import json

import pytest

import config
import platforms
import session


# ---------- 假对象 ----------
class FakeBody:
    def __init__(self, text=""):
        self.text = text


class FakeResponse:
    def __init__(self, body):
        self.body = body


class FakePacket:
    def __init__(self, body):
        self.response = FakeResponse(body)


class FakeListen:
    def __init__(self, packets=None, start_error=""):
        self._packets = list(packets or [])
        self.start_error = start_error
        self.started = []
        self.stopped = 0

    def start(self, keyword):
        if self.start_error:
            raise RuntimeError(self.start_error)
        self.started.append(keyword)

    def stop(self):
        self.stopped += 1

    def wait(self, count=1, timeout=None, fit_count=True):
        if not self._packets:
            return False
        return list(self._packets)


class FakePage:
    def __init__(self, url="https://www.zhipin.com/web/geek/job?query=python&city=101010100",
                 title="北京招聘-BOSS直聘", body_text="", cards=0, state=None,
                 packets=None, html="", start_error="", url_error=""):
        self._url = url
        self._title = title
        self._body_text = body_text
        self._cards = cards
        self._state = state
        self._html = html
        self.url_error = url_error
        self.listen = FakeListen(packets, start_error)
        self.get_urls = []
        self.scrolls = 0
        self.js_calls = []
        self.waits = []

    @property
    def url(self):
        if self.url_error:
            raise RuntimeError(self.url_error)
        return self._url

    def set_url(self, url):
        self._url = url

    @property
    def title(self):
        return self._title

    @property
    def html(self):
        return self._html

    def ele(self, selector):
        return FakeBody(self._body_text) if selector == "tag:body" else None

    def eles(self, selector):
        return [FakeBody("")] * self._cards

    def get(self, url):
        self.get_urls.append(url)

    def wait(self, seconds=None):
        self.waits.append(seconds)

    def run_js(self, js):
        self.js_calls.append(js)
        if "scrollTo" in js:
            self.scrolls += 1
            return None
        return self._state


class FakeRng:
    def __init__(self, values):
        self.values = list(values)
        self.calls = []

    def uniform(self, low, high):
        self.calls.append((low, high))
        index = len(self.calls) - 1
        return self.values[index % len(self.values)]


@pytest.fixture
def env(monkeypatch):
    """替换等待/显示/随机源/调试文件写入，返回 (events, sleeps, debug_lines)。"""
    events, sleeps, debug_lines = [], [], []

    monkeypatch.setattr(session, "_sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(session, "_set_browser_visible", lambda page, visible: False)
    monkeypatch.setattr(session, "SEARCH_RNG", FakeRng([2.1, 4.8, 3.0]))
    monkeypatch.setattr(session, "_write_debug", lambda key, lines: debug_lines.extend(lines))
    monkeypatch.setattr(session, "_LAST_SEARCH_ERROR", {})
    monkeypatch.setattr(session, "_LAST_SEARCH_DIAG", {})
    return events, sleeps, debug_lines


def install_page(monkeypatch, page):
    monkeypatch.setattr(session, "_get_page", lambda platform_key, hidden=False: page)


def run(monkeypatch, page, pages=2, platform_key="boss", cb=None):
    install_page(monkeypatch, page)
    events = cb if cb is not None else []
    jobs = session.dpage_search(platform_key, "python", pages=pages,
                               on_event=(events.append if cb is not None else None))
    return jobs, session.last_search_diagnostic(platform_key)


# ---------- 1. 导航后命中安全验证 ----------
def test_security_path_on_navigation(monkeypatch, env):
    events, sleeps, _ = env
    page = FakePage(url="https://www.zhipin.com/security-check?token=SECRET123")
    jobs, diag = run(monkeypatch, page, pages=3, cb=events)
    assert jobs == []
    assert page.scrolls == 0, "命中验证后不得继续滚动"
    assert sleeps == [], "命中验证后不得再抽样等待"
    assert diag["kind"] == "blocked_verification"
    assert diag["evidence_source"] == "url"
    assert "SECRET123" not in json.dumps(events, ensure_ascii=False, default=str)
    assert "[REDACTED]" in diag["current_url"]
    assert diag["message"].startswith("抓取到 0 个岗位")


# ---------- 2. 第二次滚动后进入验证页 ----------
def test_verification_after_second_scroll(monkeypatch, env):
    events, sleeps, _ = env
    page = FakePage()
    calls = {"n": 0}

    def fake_detect(target_page, platform_key):
        calls["n"] += 1
        # 1=导航后，2/3=第 1 轮前/后，4/5=第 2 轮前/后 → 第二次滚动后命中
        if calls["n"] == 5:
            target_page.set_url("https://www.zhipin.com/security-check?token=zzz")
            return {"kind": "blocked_verification", "evidence_source": "url",
                    "matched_rule": "url-path:security-check", "url": target_page.url}
        return None

    monkeypatch.setattr(session, "_detect_page_state", fake_detect)
    jobs, diag = run(monkeypatch, page, pages=5, cb=events)
    assert page.scrolls == 2, "命中后不得继续执行剩余 3 轮滚动"
    assert diag["kind"] == "blocked_verification"
    assert "security-check" in diag["current_url"]
    assert len(sleeps) == 2


# ---------- 3. query=security 与岗位正文不误判 ----------
def test_query_security_and_job_text_not_flagged(monkeypatch, env):
    _, _, _ = env
    page = FakePage(url="https://www.zhipin.com/web/geek/job?query=security&city=101010100",
                    body_text="验证码平台开发工程师 20-30K", packets=[])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] != "blocked_verification"

    page2 = FakePage(body_text="安全验证工程师 30-50K", cards=20, packets=[])
    _, diag2 = run(monkeypatch, page2, pages=1)
    assert diag2["kind"] != "blocked_verification", "页面有岗位卡片时不得因正文提示判风控"


# ---------- 4. URL 不变但出现可见验证弹窗 ----------
def test_visible_verification_without_url_change(monkeypatch, env):
    _ = env
    page = FakePage(body_text="请完成滑动验证后继续访问", cards=0, packets=[])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "blocked_verification"
    assert diag["evidence_source"] == "visible-text"

# ---------- 14. 命中验证时显示浏览器窗口，交人工处理 ----------
def test_surface_on_verification(monkeypatch, env):
    events, _, debug_lines = env
    calls = {"n": 0}

    def fake_surface(platform_key, page=None, left=120, top=80):
        calls["n"] += 1
        return True, "验证页面已显示到桌面"

    monkeypatch.setattr(session, "surface_verification_page", fake_surface)
    page = FakePage(url="https://www.zhipin.com/security-check?token=zzz")
    jobs, diag = run(monkeypatch, page, pages=2, cb=events)
    assert calls["n"] == 1, "命中验证应把窗口显示出来一次"
    assert diag["surfaced"] is True
    assert "已显示到桌面" in diag["message"]
    assert any("验证页展示: 成功" in line for line in debug_lines)


def test_surface_skipped_when_disabled(monkeypatch, env):
    _ = env
    calls = {"n": 0}
    monkeypatch.setattr(session, "surface_verification_page",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), (True, ""))[1])
    monkeypatch.setattr(config, "SURFACE_ON_VERIFICATION", False)
    page = FakePage(url="https://www.zhipin.com/security-check")
    _, diag = run(monkeypatch, page, pages=1)
    assert calls["n"] == 0
    assert diag["surfaced"] is False


def test_surface_failure_message(monkeypatch, env):
    _ = env
    monkeypatch.setattr(session, "surface_verification_page",
                        lambda *a, **k: (False, "浏览器窗口无法自动显示"))
    page = FakePage(url="https://www.zhipin.com/security-check")
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["surfaced"] is False
    assert "无法自动显示" in diag["message"]


def test_wait_verification_done(monkeypatch):
    monkeypatch.setattr(session, "_sleep", lambda seconds: None)
    page = FakePage()
    states = {"n": 0}

    def fake_detect(target_page, platform_key):
        states["n"] += 1
        return None if states["n"] > 2 else {"kind": "blocked_verification",
                                             "evidence_source": "url",
                                             "matched_rule": "url-path:security",
                                             "url": "https://www.zhipin.com/security"}
    monkeypatch.setattr(session, "_detect_page_state", fake_detect)
    done, detail = session.wait_verification_done("boss", timeout=5, interval=1, page=page)
    assert done is True
    assert "已离开" in detail


def test_wait_verification_timeout(monkeypatch):
    monkeypatch.setattr(session, "_sleep", lambda seconds: None)
    monkeypatch.setattr(session, "_detect_page_state",
                        lambda page, key: {"kind": "blocked_verification",
                                           "evidence_source": "url",
                                           "matched_rule": "url-path:security",
                                           "url": ""})
    page = FakePage()
    done, detail = session.wait_verification_done("boss", timeout=1, interval=1, page=page)
    assert done is False
    assert "超时" in detail



# ---------- 5. 隐藏脚本内容不触发 ----------
def test_hidden_script_text_not_flagged(monkeypatch, env):
    _ = env
    page = FakePage(body_text="", html="<script>var t='安全验证'</script>", packets=[])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] != "blocked_verification"


# ---------- 6. 只有弱线索“请稍候”不判定风控 ----------
def test_weak_hint_does_not_block(monkeypatch, env):
    _ = env
    page = FakePage(body_text="请稍候，正在加载", cards=0, packets=[])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "no_packet"
    assert "请稍候" in diag["message"]


# ---------- 7. 五类“没有岗位”的原因区分 ----------
def test_empty_list(monkeypatch, env):
    _ = env
    page = FakePage(packets=[FakePacket({"code": 0, "zpData": {"jobList": []}})])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "empty_result"


def test_missing_structure(monkeypatch, env):
    _ = env
    page = FakePage(packets=[FakePacket({"code": 0, "zpData": {}})])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "parse_empty"


def test_api_error(monkeypatch, env):
    _ = env
    page = FakePage(packets=[FakePacket({"code": 37, "message": "需要安全验证"})])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "api_error"
    assert diag["api_code"] == 37
    assert "封号" not in diag["message"], "不得把未知非零码解释为封号"


def test_filtered_empty(monkeypatch, env):
    _ = env
    page = FakePage(packets=[FakePacket({"code": 0, "zpData": {"jobList": [
        {"jobName": "已沟通岗位", "brandName": "甲公司", "contact": True,
         "encryptJobId": "abc"},
    ]}})])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "filtered_empty"
    assert diag["raw_job_count"] == 1 and diag["filtered_contact_count"] == 1


def test_no_packet(monkeypatch, env):
    _ = env
    page = FakePage(packets=[])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "no_packet"
    assert diag["packet_count"] == 0


# ---------- 8. 浏览器不可用 / URL 读取失败 ----------
def test_browser_unavailable(monkeypatch, env):
    events, _, _ = env

    def boom(platform_key, hidden=False):
        raise RuntimeError("浏览器启动失败，请检查浏览器配置")

    monkeypatch.setattr(session, "_get_page", boom)
    jobs = session.dpage_search("boss", "python", pages=1, on_event=events.append)
    diag = session.last_search_diagnostic("boss")
    assert jobs == []
    assert diag["kind"] == "browser_unavailable"
    assert "浏览器启动失败" in diag["message"]
    assert diag["url_read_error"] == ""
    assert diag["requested_url"], "浏览器没起来时至少要有请求地址"


def test_url_read_failure_keeps_reason(monkeypatch, env):
    _ = env
    page = FakePage(url_error="target closed", packets=[FakePacket({"code": 0, "zpData": {"jobList": []}})])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["url_read_error"]
    assert diag["kind"] == "empty_result", "URL 读不到不得覆盖更明确的原因"
    assert diag["last_observed_url"] != "" or diag["current_url"] == ""


# ---------- 9. 已有岗位随后命中验证：partial 保留 ----------
def test_partial_keeps_jobs(monkeypatch, env):
    events, _, _ = env
    page = FakePage(packets=[FakePacket({"code": 0, "zpData": {"jobList": [
        {"jobName": "后端工程师", "brandName": "乙公司", "encryptJobId": "job-1", "contact": False},
    ]}})])
    calls = {"n": 0}

    def fake_detect(target_page, platform_key):
        calls["n"] += 1
        if calls["n"] == 3:
            target_page.set_url("https://www.zhipin.com/security-check")
            return {"kind": "blocked_verification", "evidence_source": "url",
                    "matched_rule": "url-path:security-check", "url": target_page.url}
        return None

    monkeypatch.setattr(session, "_detect_page_state", fake_detect)
    jobs, diag = run(monkeypatch, page, pages=3, cb=events)
    assert len(jobs) == 1
    assert diag["partial"] is True
    assert "已获取 1 条" in diag["message"]
    assert session.last_search_error("boss") == diag["message"], "部分完成必须保留警告"


# ---------- 10. 每轮独立随机等待 ----------
def test_random_interval_per_round(monkeypatch, env):
    _, sleeps, _ = env
    page = FakePage(packets=[])
    _, diag = run(monkeypatch, page, pages=3)
    assert page.scrolls == 3
    assert sleeps == [2.1, 4.8, 3.0], "每轮都要独立抽样并在动作前等待"
    assert diag["scroll_intervals"] == [2.1, 4.8, 3.0]


def test_interval_bounds_config_error(monkeypatch, env):
    _ = env
    monkeypatch.setattr(config, "SEARCH_SCROLL_INTERVAL_MIN", "0")
    page = FakePage(packets=[])
    _, diag = run(monkeypatch, page, pages=1)
    assert diag["kind"] == "search_error"
    assert "配置" in diag["message"]
    assert page.get_urls == [], "配置非法时不得启动抓取"


@pytest.mark.parametrize("low,high", [("-1", "5"), ("0", "5"), ("5", "2"),
                                      ("abc", "5"), ("nan", "5"), ("1", "inf")])
def test_bounds_validation(monkeypatch, low, high):
    monkeypatch.setattr(config, "SEARCH_SCROLL_INTERVAL_MIN", low)
    monkeypatch.setattr(config, "SEARCH_SCROLL_INTERVAL_MAX", high)
    with pytest.raises(ValueError):
        config.search_scroll_bounds()


# ---------- 11. 同平台互斥 ----------
def test_concurrent_search_rejected(monkeypatch, env):
    _ = env
    page = FakePage(packets=[])
    install_page(monkeypatch, page)
    lock = session._search_lock("boss")
    assert lock.acquire(blocking=False)
    try:
        jobs = session.dpage_search("boss", "python", pages=1)
    finally:
        lock.release()
    assert jobs == []
    assert "正在检索" in session.last_search_error("boss")
    # 下一轮不残留上次的诊断
    session.dpage_search("boss", "python", pages=1)
    diag = session.last_search_diagnostic("boss")
    assert diag["packet_count"] == 0
    assert "正在检索" not in diag["message"]


# ---------- 12. 脱敏 ----------
def test_redact_url():
    url = ("https://user:pass@www.zhipin.com/web/geek/job?query=python&city=101010100"
           "&token=SECRET&ticket=TICKET#frag")
    text = session._redact_url(url)
    assert "SECRET" not in text and "TICKET" not in text and "pass" not in text
    assert "frag" not in text
    assert "query=python" in text and "city=101010100" in text
    assert "[REDACTED]" in text


def test_debug_file_has_no_secret(monkeypatch, env):
    _, _, debug_lines = env
    page = FakePage(url="https://www.zhipin.com/security-check?token=SECRET123")
    run(monkeypatch, page, pages=1)
    joined = "\n".join(debug_lines)
    assert "SECRET123" not in joined
    assert "[REDACTED]" in joined


# ---------- 13. 回调与格式化 ----------
def test_callback_error_does_not_break(monkeypatch, env):
    _ = env

    def boom(event):
        raise RuntimeError("GUI 已关闭")

    page = FakePage(packets=[])
    install_page(monkeypatch, page)
    jobs = session.dpage_search("boss", "python", pages=1, on_event=boom)
    assert jobs == []
    assert session.last_search_diagnostic("boss")["kind"] == "no_packet"


def test_format_event_lines():
    import loop
    event = {"platform": "boss", "kind": "blocked_verification",
             "message": "抓取到 0 个岗位：检测到疑似安全验证页面，已停止本轮抓取",
             "matched_rule": "url-path:security-check", "stage": "滚动后(#2)",
             "current_url": "https://www.zhipin.com/security-check?token=[REDACTED]",
             "requested_url": "https://www.zhipin.com/web/geek/job?query=python",
             "partial": False, "result_count": 0}
    lines = loop.format_event(event)
    joined = "\n".join(lines)
    assert "抓取到 0 个岗位" in joined
    assert "判断依据：url-path:security-check（阶段：滚动后(#2)）" in joined
    assert "当前页面：https://www.zhipin.com/security-check" in joined
    assert "人工处理" in joined
