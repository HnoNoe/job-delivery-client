# -*- coding: utf-8 -*-
"""
check_env.py —— 环境自检
=========================
检查运行前必须满足的条件，缺什么直接告诉你装什么。

    python check_env.py            静态检查
    python check_env.py --online   顺带检查登录态（会开一下浏览器）
"""

import importlib
import socket
import sys
from pathlib import Path

import config
import browser as br_mod

ROOT = Path(__file__).resolve().parent


def fix_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def mark(ok, text, hint=""):
    print(("  ✅ " if ok else "  ❌ ") + text + (("  -> " + hint) if (not ok and hint) else ""))
    return ok


def port_busy(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", int(port))) == 0


def main(argv=None):
    fix_console()
    print("=" * 58)
    print("  BOSS直聘采集器 环境自检")
    print("=" * 58)
    ok_all = True

    print("\n[1] Python")
    ok_all &= mark(sys.version_info >= (3, 8), "Python %s" % sys.version.split()[0], "需要 3.8+")

    print("\n[2] 依赖")
    for name, hint in (("websocket", 'pip install websocket-client'),
                       ("openpyxl", "pip install openpyxl（没有也能跑，只是不生成 Excel）")):
        try:
            importlib.import_module(name)
            mark(True, name + " 已安装")
        except ImportError:
            ok_all &= mark(False, name + " 没装", hint)

    print("\n[3] 浏览器")
    chrome = br_mod.find_chrome()
    ok_all &= mark(bool(chrome), "找到浏览器：%s" % (chrome or "（无）"),
                   '装个 Chrome，或用 --chrome "C:\\路径\\chrome.exe" 指定')

    print("\n[4] 端口与 profile")
    busy = port_busy(config.DEFAULT_PORT)
    mark(True, "调试端口 %d：%s" % (config.DEFAULT_PORT, "已被占用（会复用）" if busy else "空闲"))
    profile = ROOT / config.BROWSER_PROFILE
    mark(True, "profile 目录：%s%s" % (profile, "" if profile.exists() else "（还没创建，首次运行会建）"))

    print("\n[5] 输出目录")
    for sub in ("output", "raw"):
        path = ROOT / sub
        path.mkdir(parents=True, exist_ok=True)
        mark(True, "%s 就绪" % path.name)

    if "--online" in (argv or sys.argv[1:]):
        print("\n[6] 登录态")
        try:
            import parser
            br = br_mod.Browser(port=config.DEFAULT_PORT, profile_dir=profile, hidden=True)
            ok, msg = br.ensure_running()
            if ok:
                ok2, _ = br.attach()
                if ok2:
                    br.goto("https://www.zhipin.com/web/geek/jobs", settle=6.0)
                    state = parser.read_state(br.evaluate(parser.LOGIN_STATE_JS))
                    ok_all &= mark(bool(state.get("loggedIn")),
                                   "登录态：%s" % (state.get("name") or "未登录"),
                                   "python main.py login")
            br.close()
        except Exception as exc:  # noqa: BLE001
            ok_all &= mark(False, "在线检查失败：%s" % exc)

    print("\n" + "=" * 58)
    print(("  ✅ 全部就绪，可以跑：python main.py search" if ok_all
           else "  ⚠️ 有项目没通过，按上面提示处理后再试"))
    print("=" * 58)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
