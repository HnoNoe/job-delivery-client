# -*- coding: utf-8 -*-
"""
menu.py —— 图形化菜单（双击 启动.bat 时调用）
==============================================
批处理对中文编码敏感，所以中文菜单放在 Python 里，避免乱码。

也可以带参数直接跑：
    python menu.py check    环境自检
    python menu.py search   开始抓取
    python menu.py login    登录
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

MENU = """
====================================================
        BOSS直聘 岗位采集（CDP 旁听版）
====================================================
  1. 环境自检（第一次请先运行这个）
  2. 登录 BOSS 账号（只在首次 / 掉登录后需要）
  3. 开始抓取岗位（默认 6 关键词 × 8 城市 × 1 页）
  4. 补岗位详情（判定投递入口）
  5. 抓 HR 沟通过列表
  6. 打开输出文件夹
  7. 安装依赖
  0. 退出
===================================================="""


def setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def clear():
    if os.name == "nt":
        os.system("cls")


def pause():
    if os.environ.get("NO_PAUSE"):
        return
    try:
        input("\n按回车键返回菜单...")
    except (EOFError, KeyboardInterrupt):
        pass


def run(args):
    return subprocess.call([sys.executable, *args], cwd=str(ROOT))


def do_check():
    print(">>> 环境自检\n")
    return run(["check_env.py"])


def do_login():
    print(">>> 打开登录页：会弹出一个浏览器窗口，扫码登录后回到这里按回车\n")
    return run(["main.py", "login"])


def do_search():
    print(">>> 开始抓取岗位")
    print("提示：浏览器窗口默认隐藏（最小化），抓完自动关闭并生成 Excel。\n")
    return run(["main.py", "search", "--open"])


def do_detail():
    print(">>> 给前几条岗位补详情、判定投递入口\n")
    return run(["main.py", "detail", "-n", "5"])


def do_chat():
    print(">>> 抓 HR 沟通过列表\n")
    return run(["main.py", "chat"])


def do_deps():
    print(">>> 安装依赖（pip install -r requirements.txt）\n")
    return run(["-m", "pip", "install", "-r", "requirements.txt"])


def do_open():
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    from utils import open_path
    open_path(out)
    return 0


ACTIONS = {
    "1": do_check, "check": do_check,
    "2": do_login, "login": do_login,
    "3": do_search, "search": do_search,
    "4": do_detail, "detail": do_detail,
    "5": do_chat, "chat": do_chat,
    "6": do_open, "7": do_deps,
}


def main(argv=None):
    setup_console()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        action = ACTIONS.get(argv[0])
        return action() if action else 1
    while True:
        clear()
        print(MENU)
        try:
            choice = input("请输入序号：").strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        if choice in ("0", ""):
            return 0
        action = ACTIONS.get(choice)
        if not action:
            print("没有这个选项。")
            pause()
            continue
        action()
        pause()


if __name__ == "__main__":
    sys.exit(main())
