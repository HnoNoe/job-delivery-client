# -*- coding: utf-8 -*-
"""
browser.py —— 浏览器驱动（CDP）
================================
用你自己电脑上的 Chrome/Edge，通过调试端口接管它：
    · 只需要 websocket-client 一个依赖，不装 Playwright/Selenium
    · 默认隐藏窗口（最小化），任务结束自动关闭浏览器
    · 不加 --headless、不加 webdriver 标记，正常浏览器指纹，反爬不易识别

为什么不用 headless：BOSS 会直接判定环境异常（跳安全验证页），实测不可用。
"""
import ctypes
import json
import os
import subprocess
import time
import urllib.request
from ctypes import wintypes
from pathlib import Path

import config

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
SW_MINIMIZE = 6
SW_RESTORE = 9


def find_chrome():
    """找一个可用的 Chromium 内核浏览器。"""
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return ""


def _http_json(port, path, timeout=3.0):
    url = "http://127.0.0.1:%d%s" % (int(port), path)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _windows_of(pid):
    """枚举某进程的可见顶层窗口（Windows）。"""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    handles = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            handles.append(hwnd)
        return True

    user32.EnumWindows(proto(_cb), 0)
    return handles


def _set_window_state(pid, cmd):
    if os.name != "nt":
        return False
    try:
        handles = _windows_of(pid)
        for hwnd in handles:
            ctypes.windll.user32.ShowWindow(hwnd, cmd)
        return bool(handles)
    except Exception:  # noqa: BLE001
        return False


class Browser:
    """一台由本模块管理的 CDP 浏览器；支持 with 语句自动关闭。"""

    def __init__(self, port=None, profile_dir=None, chrome_exe=None,
                 hidden=True, keep_open=False):
        self.port = int(port or config.DEFAULT_PORT)
        self.profile_dir = Path(profile_dir) if profile_dir else Path(config.BROWSER_PROFILE)
        self.chrome_exe = chrome_exe or find_chrome()
        self.hidden = hidden
        self.keep_open = keep_open
        self.proc = None
        self.ws = None
        self._seq = 0
        self._spawned = False

    # ---------- 生命周期 ----------
    def running(self):
        try:
            return bool(_http_json(self.port, "/json/version", timeout=1.5).get("Browser"))
        except Exception:  # noqa: BLE001
            return False

    def ensure_running(self):
        """已在跑就复用，否则拉起一个（默认隐藏窗口的）浏览器。"""
        if self.running():
            return True, "复用已运行的浏览器（端口 %d）" % self.port
        if not self.chrome_exe:
            return False, "找不到 Chrome/Edge，可用 --chrome 指定路径"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            self.chrome_exe,
            "--remote-debugging-port=%d" % self.port,
            "--remote-allow-origins=*",
            "--user-data-dir=%s" % self.profile_dir.resolve(),
            "--no-first-run", "--no-default-browser-check",
            "--window-size=1440,900",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "about:blank",
        ]
        self.proc = subprocess.Popen(args, close_fds=True)
        self._spawned = True
        for _ in range(40):
            if self.running():
                break
            time.sleep(0.5)
        else:
            return False, "浏览器端口 %d 未就绪" % self.port
        if self.hidden:
            time.sleep(0.8)
            _set_window_state(self.proc.pid, SW_MINIMIZE)
        return True, "已启动浏览器（端口 %d，profile=%s）" % (self.port, self.profile_dir)

    def attach(self):
        """附着到第一个页面目标并开启 Network 域（只旁听，不注入脚本）。"""
        try:
            targets = _http_json(self.port, "/json/list")
        except Exception as exc:  # noqa: BLE001
            return False, "读取目标列表失败：%s" % exc
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            return False, "没有可用的页面目标"
        import websocket

        self.ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"],
                                              timeout=10, suppress_origin=True)
        self._send("Network.enable", {"maxTotalBufferSize": 100 * 1024 * 1024,
                                      "maxResourceBufferSize": 20 * 1024 * 1024})
        self._recv(1.0)
        return True, "已附着页面目标"

    def close(self):
        """关闭浏览器：只关自己拉起的那个。"""
        try:
            if self.ws is not None:
                self.ws.close()
        except Exception:  # noqa: BLE001
            pass
        self.ws = None
        if not self._spawned or self.keep_open:
            return True, "已断开连接（浏览器保持运行）"
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=8)
            except Exception:  # noqa: BLE001
                try:
                    self.proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        return True, "已关闭浏览器"

    def show(self):
        return _set_window_state(self.proc.pid, SW_RESTORE) if self.proc else False

    def hide(self):
        return _set_window_state(self.proc.pid, SW_MINIMIZE) if self.proc else False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    # ---------- CDP 原语 ----------
    def _send(self, method, params=None):
        self._seq += 1
        self.ws.send(json.dumps({"id": self._seq, "method": method, "params": params or {}}))
        return self._seq

    def _recv(self, duration):
        events = []
        end = time.time() + float(duration)
        while time.time() < end:
            try:
                self.ws.settimeout(max(0.2, end - time.time()))
                raw = self.ws.recv()
            except Exception:  # noqa: BLE001
                continue
            if not raw:
                continue
            try:
                events.append(json.loads(raw))
            except Exception:  # noqa: BLE001
                continue
        return events

    def _body(self, request_id):
        mid = self._send("Network.getResponseBody", {"requestId": request_id})
        for msg in self._recv(3.0):
            if msg.get("id") == mid:
                return (msg.get("result") or {}).get("body") or ""
        return ""

    def evaluate(self, expression):
        """在页面里执行表达式（只读用途：取元素位置/文案）。"""
        mid = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        for msg in self._recv(6.0):
            if msg.get("id") == mid:
                value = ((msg.get("result") or {}).get("result") or {}).get("value")
                return value if value is not None else ""
        return ""

    # ---------- 业务动作 ----------
    def goto(self, url, match=(), settle=8.0, fresh=True):
        """打开页面并收集 URL 含 match 关键字的响应体。

        fresh=True 会先跳 about:blank：BOSS 搜索页只有整页重载才会请求 joblist 接口。
        """
        events = []
        if fresh:
            self._send("Page.navigate", {"url": "about:blank"})
            events.extend(self._recv(1.0))
        self._send("Page.navigate", {"url": url})
        events.extend(self._recv(settle))
        if not match:
            return []
        wanted = {}
        for msg in events:
            if msg.get("method") != "Network.requestWillBeSent":
                continue
            params = msg.get("params") or {}
            req_url = ((params.get("request") or {}).get("url") or "")
            if any(key in req_url for key in match):
                wanted[params.get("requestId")] = req_url
        out, seen = [], set()
        for msg in events:
            if msg.get("method") != "Network.loadingFinished":
                continue
            rid = (msg.get("params") or {}).get("requestId")
            if rid not in wanted or rid in seen:
                continue
            seen.add(rid)
            body = self._body(rid)
            if body:
                out.append({"url": wanted[rid], "body": body})
        return out

    def bring_to_front(self):
        self._send("Page.bringToFront")
        self._recv(0.5)
        if self.proc is not None and os.name == "nt":
            try:
                for hwnd in _windows_of(self.proc.pid):
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass
        return True

    def press_escape(self):
        """按 Esc 关掉遮挡按钮的浮层。"""
        for kind in ("rawKeyDown", "keyUp"):
            self._send("Input.dispatchKeyEvent", {"type": kind, "key": "Escape", "code": "Escape",
                                                  "windowsVirtualKeyCode": 27,
                                                  "nativeVirtualKeyCode": 27})
        self._recv(0.5)
        return True

    def click_selector(self, selector, retries=1):
        """点击 CSS 选择器命中的元素中心；落点被遮挡时先 Esc 再重试。"""
        expr = (
            "(function(){var b=document.querySelector(%s);if(!b)return JSON.stringify({ok:false,why:'no-el'});"
            "b.scrollIntoView({block:'center'});var r=b.getBoundingClientRect();"
            "var x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2);"
            "var el=document.elementFromPoint(x,y);"
            "return JSON.stringify({ok:!!el&&(b===el||b.contains(el)),x:x,y:y,"
            "label:(b.innerText||'').trim().slice(0,12)});})()"
        ) % json.dumps(selector)
        info = {}
        for attempt in range(retries + 1):
            try:
                info = json.loads(self.evaluate(expr) or "{}")
            except Exception:  # noqa: BLE001
                info = {}
            if info.get("ok"):
                break
            if attempt < retries:
                self.press_escape()
                self._recv(0.8)
        if not info.get("ok"):
            reason = "元素不存在" if info.get("why") == "no-el" else "落点被其他元素遮挡"
            return False, "点击失败（%s：%s）" % (selector, reason)
        x, y = info["x"], info["y"]
        self._send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "none"})
        self._recv(0.2)
        self._send("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y,
                                                "button": "left", "clickCount": 1})
        self._recv(0.08)
        self._send("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y,
                                                "button": "left", "clickCount": 1})
        self._recv(0.3)
        return True, "已点击「%s」于 (%d, %d)" % (info.get("label") or selector, x, y)
