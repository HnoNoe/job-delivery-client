# -*- coding: utf-8 -*-
"""cdp_procs.py —— Windows 下查询/结束占用 CDP 调试端口的 Chrome 进程。

单独成文件是为了把 PowerShell 脚本的引号问题隔离在一处：
写临时 .ps1 再执行，避免 -Command 的多层转义。
"""

import os
import subprocess
import tempfile

_PS_TEMPLATE = "\n".join([
    "$OutputEncoding = [Console]::OutputEncoding = [Text.Encoding]::UTF8",
    "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" |",
    "  Where-Object { $_.CommandLine -like '*remote-debugging-port=__PORT__*' } |",
    "  ForEach-Object { [string]$_.ProcessId + '|' + [string]$_.CommandLine }",
    "",
])


def running_chrome_procs(port):
    """-> [(pid, user_data_dir)]，只返回占用该调试端口的 chrome。"""
    if os.name != "nt":
        return []
    script = _PS_TEMPLATE.replace("__PORT__", str(int(port)))
    path = os.path.join(tempfile.gettempdir(), "jobdelivery_cdp_proc.ps1")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(script)
        out = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path],
                             capture_output=True, timeout=40)
        text = out.stdout.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return []
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if "|" not in line:
            continue
        pid_text, _, cmdline = line.partition("|")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        marker = "--user-data-dir="
        idx = cmdline.find(marker)
        data_dir = cmdline[idx + len(marker):].split(" --")[0].strip().strip('"') if idx >= 0 else ""
        rows.append((pid, data_dir))
    return rows


def kill_pid(pid):
    """强杀进程（仅用于关掉我们自己拉起的浏览器）。"""
    try:
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/F"],
                       capture_output=True, timeout=15)
        return True
    except Exception:  # noqa: BLE001
        return False
