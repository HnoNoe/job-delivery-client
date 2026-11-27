# -*- coding: utf-8 -*-
"""
utils.py —— 通用小工具
=======================
编码修正、日志、打开目录、解析逗号分隔列表。
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def fix_console_encoding():
    """Windows 控制台默认 GBK，统一改成 UTF-8，避免中文乱码。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def get_logger(root, name="boss"):
    """同时写文件和控制台的简易日志器。"""
    import logging

    root = Path(root)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    try:
        fh = logging.FileHandler(root / "运行日志.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:  # noqa: BLE001
        pass
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


def parse_list(text):
    """把 "Python,Java" 或 "Python，Java" 拆成列表。"""
    items = [x.strip() for x in str(text or "").replace("，", ",").split(",")]
    return [x for x in items if x]


def open_path(path):
    """用系统默认程序打开文件或文件夹。"""
    path = str(path)
    if os.name == "nt":
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.call(["open", path])
    else:
        subprocess.call(["xdg-open", path])


def sleep_between(min_delay, max_delay):
    """在 [min, max] 之间随机等待，降低请求节奏风险。"""
    import random

    time.sleep(random.uniform(min_delay, max_delay))


def safe_filename(value, limit=80):
    """把任意字符串变成安全的文件名。"""
    import re

    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "未命名"))
    return name.strip(" .")[:limit].rstrip(" .") or "未命名"
