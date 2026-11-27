"""CDP 浏览器桥：用本机 Chrome + 持久化 profile 驱动真实浏览器，只开 Network 域旁听。

设计约束（均为实测结论）：
- 调试端口必须在启动时加，运行中的浏览器无法热开，所以浏览器由本模块拉起；
- 默认隐藏窗口（最小化），任务结束后默认关闭本模块拉起的浏览器；
- 不加 --headless、不加 --test-type=webdriver（BOSS 会判 code=36 直接跳校验页）；
- 只做导航与响应读取，不注入脚本、不派遣额外业务请求。
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
from logging_setup import get_logger

log = get_logger(__name__)

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

SW_MINIMIZE = 6
DEFAULT_PORT = 9222


def find_chrome():
    """找一个可用的 Chromium 内核浏览器路径。"""
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    return ""


def _http_json(port, path, timeout=3.0):
    url = "http://127.0.0.1:%d%s" % (port, path)
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _windows_of(pid):
    """枚举某进程的可见顶层窗口句柄（Windows only）。"""
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


def hide_window(pid):
    """把进程主窗口最小化；失败返回 False（不影响抓取）。"""
    if os.name != "nt":
        return False
    try:
        handles = _windows_of(pid)
        for hwnd in handles:
            ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
        return bool(handles)
    except Exception as exc:  # noqa: BLE001
        log.warning("隐藏窗口失败：%s", exc)
        return False


def show_window(pid):
    """把进程主窗口恢复显示（投递点击前需要真实窗口）。"""
    if os.name != "nt":
        return False
    try:
        handles = _windows_of(pid)
        for hwnd in handles:
            ctypes.windll.user32.ShowWindow(hwnd, 9)   # SW_RESTORE
        return bool(handles)
    except Exception as exc:  # noqa: BLE001
        log.warning("恢复窗口失败：%s", exc)
        return False


PROFILE_POINTER = Path(config.RUNTIME_DIR) / "browser" / "default_profile.json"


def running_chrome_procs(port):
    """查占用该调试端口的 chrome 进程 -> [(pid, user_data_dir)]。"""
    try:
        from cdp_procs import running_chrome_procs as _impl
        return _impl(port)
    except Exception:  # noqa: BLE001
        return []


def load_default_profile(platform_key):
    """读上次记住的 profile（没有就返回 None）。"""
    try:
        data = json.loads(PROFILE_POINTER.read_text(encoding="utf-8"))
        path = (data or {}).get(platform_key)
        if path and Path(path).exists():
            return path
    except Exception:  # noqa: BLE001
        pass
    return None


def remember_profile(platform_key, path):
    """记住某平台要用的 profile，后续命令不必再传 --profile。"""
    try:
        data = {}
        if PROFILE_POINTER.exists():
            data = json.loads(PROFILE_POINTER.read_text(encoding="utf-8")) or {}
        data[platform_key] = str(Path(path))
        PROFILE_POINTER.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_POINTER.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


class CdpBrowser:
    """一台由本模块管理的 CDP 浏览器。用 with 语句可自动关闭。"""

    def __init__(self, platform_key="boss", port=DEFAULT_PORT, profile_dir=None,
                 chrome_exe=None, hidden=True, keep_open=False):
        self.platform_key = platform_key
        self.port = int(port)
        remembered = load_default_profile(platform_key) if not profile_dir else None
        self.profile_dir = Path(profile_dir) if profile_dir else (
            Path(remembered) if remembered else
            Path(config.RUNTIME_DIR) / "browser" / platform_key / "profile")
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
            info = _http_json(self.port, "/json/version", timeout=1.5)
            return bool(info.get("Browser"))
        except Exception:  # noqa: BLE001
            return False

    def ensure_running(self):
        """确保调试端口可用：已在跑就复用，否则拉起一个隐藏窗口的浏览器。"""
        procs = running_chrome_procs(self.port) if self.running() else []
        if procs:
            want = os.path.normcase(os.path.abspath(str(self.profile_dir)))
            dirs = [os.path.normcase(os.path.abspath(d)) for _pid, d in procs if d]
            if not dirs or want in dirs:
                note = "" if dirs else "（端口占用，profile 未知）"
                return True, "复用已运行的浏览器（端口 %d，profile=%s）%s" % (
                    self.port, self.profile_dir, note)
            # 端口被另一个 profile 的浏览器占着：关掉它，否则 --profile 会静默失效
            for pid, _d in procs:
                try:
                    subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                                   capture_output=True, timeout=15)
                except Exception:  # noqa: BLE001
                    pass
            for _ in range(20):
                if not self.running():
                    break
                time.sleep(0.5)
        if not self.chrome_exe:
            return False, "找不到 Chrome/Edge，可用 --chrome 指定路径"
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        args = [
            self.chrome_exe,
            "--remote-debugging-port=%d" % self.port,
            "--remote-allow-origins=*",
            "--user-data-dir=%s" % self.profile_dir,
            "--no-first-run", "--no-default-browser-check",
            "--window-size=1440,900",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "about:blank",
        ]
        log.info("启动浏览器：%s（profile=%s）", self.chrome_exe, self.profile_dir)
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
            if hide_window(self.proc.pid):
                log.info("浏览器窗口已隐藏")
        return True, "已启动浏览器（端口 %d，profile=%s）" % (self.port, self.profile_dir)

    def attach(self):
        """附着到第一个 page 目标并开启 Network 域。"""
        try:
            targets = _http_json(self.port, "/json/list")
        except Exception as exc:  # noqa: BLE001
            return False, "读取目标列表失败：%s" % exc
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            return False, "没有可用的页面目标"
        import websocket  # 延迟导入，未装依赖时只影响浏览器能力
        self.ws = websocket.create_connection(pages[0]["webSocketDebuggerUrl"],
                                              timeout=10, suppress_origin=True)
        self._send("Network.enable", {"maxTotalBufferSize": 100 * 1024 * 1024,
                                      "maxResourceBufferSize": 20 * 1024 * 1024})
        self._recv(1.0)
        return True, "已附着页面目标"

    def show(self):
        """临时显示窗口（点击类操作需要真实窗口）。"""
        return show_window(self.proc.pid) if self.proc is not None else False

    def hide(self):
        """重新隐藏窗口。"""
        return hide_window(self.proc.pid) if self.proc is not None else False

    def close(self):
        """关闭浏览器：本模块拉起的才关，别人开着的只断开连接。"""
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
        """在 duration 秒内收集所有事件/响应。"""
        events = []
        end = time.time() + float(duration)
        while time.time() < end:
            try:
                self.ws.settimeout(max(0.2, end - time.time()))
                raw = self.ws.recv()
            except Exception:  # noqa: BLE001  超时或关闭
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

    # ---------- 业务动作 ----------
    def goto(self, url, match=(), settle=8.0, fresh=True):
        """导航到 url 并收集匹配 match 关键字的响应体。

        fresh=True 时先跳到 about:blank：BOSS 的搜索页只有在整页重载时才会请求
        joblist 接口（SPA 内部改 query 不会触发）。
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
            req = msg.get("params") or {}
            req_url = ((req.get("request") or {}).get("url") or "")
            if any(key in req_url for key in match):
                wanted[req.get("requestId")] = req_url
        out = []
        for msg in events:
            if msg.get("method") != "Network.loadingFinished":
                continue
            rid = (msg.get("params") or {}).get("requestId")
            if rid not in wanted or rid in {item["requestId"] for item in out}:
                continue
            body = self._body(rid)
            if body:
                out.append({"url": wanted[rid], "requestId": rid, "body": body})
        return out

    def bring_to_front(self):
        """把页面所在窗口提到前台（点击前的焦点保证）。"""
        self._send("Page.bringToFront")
        self._recv(0.5)
        if self.proc is not None:
            try:
                for hwnd in _windows_of(self.proc.pid):
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:  # noqa: BLE001
                pass
        return True

    def press_escape(self):
        """按一次 Esc（用于关掉遮挡投递按钮的浮层）。"""
        for kind in ("rawKeyDown", "keyUp"):
            self._send("Input.dispatchKeyEvent", {"type": kind, "key": "Escape",
                                                  "code": "Escape",
                                                  "windowsVirtualKeyCode": 27,
                                                  "nativeVirtualKeyCode": 27})
        self._recv(0.5)
        return True

    def click_selector(self, selector, retries=1):
        """按 CSS 选择器点击元素中心（可信输入事件）。返回 (ok, msg)。

        先用 elementFromPoint 校验落点确实是该元素，避免点错位置。
        """
        expr = (
            "(function(){var b=document.querySelector(%s);if(!b)return JSON.stringify({ok:false,why:'no-el'});"
            "b.scrollIntoView({block:'center'});var r=b.getBoundingClientRect();"
            "var x=Math.round(r.x+r.width/2),y=Math.round(r.y+r.height/2);"
            "var el=document.elementFromPoint(x,y);"
            "return JSON.stringify({ok:!!el&&(b===el||b.contains(el)),x:x,y:y,label:(b.innerText||'').trim().slice(0,12)});})()"
        ) % json.dumps(selector)
        info = {}
        for attempt in range(retries + 1):
            raw = self.evaluate(expr)
            try:
                info = json.loads(raw or "{}")
            except Exception:  # noqa: BLE001
                info = {}
            if info.get("ok"):
                break
            if attempt < retries:
                # 常见原因是简历完善/引导浮层盖住按钮，Esc 关掉后重试
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

    def evaluate(self, expression):
        """在页面里求值（只读用途：取元素位置与文本）。返回字符串。"""
        mid = self._send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        for msg in self._recv(6.0):
            if msg.get("id") != mid:
                continue
            result = (msg.get("result") or {}).get("result") or {}
            value = result.get("value")
            return value if value is not None else ""
        return ""
