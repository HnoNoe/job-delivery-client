# -*- mode: python ; coding: utf-8 -*-
"""智投链本地客户端 · PyInstaller 规格（单文件便携版）。

用法：
    pyinstaller client.spec --noconfirm --clean
产出：
    dist\\智投链客户端.exe

安全要点：secrets_local.py（DeepSeek 密钥）绝不打入公开发布的 exe——
仓库与 Release 均为公开，内置密钥等于把 API 额度送出去。
需要 AI 识别时在系统环境变量 JOBDELIVERY_DEEPSEEK_KEY 配置即可（无密钥自动回退规则引擎）。
"""
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

datas, binaries, hiddenimports = [], [], []

# 第三方包整包收集：目标机器无需安装 Python 依赖
for pkg in ("DrissionPage", "selenium", "reportlab", "browser_cookie3",
            "pypdf", "bs4", "requests"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

# 运行时通过 importlib.metadata 读版本号的包，必须带元数据
for pkg in ("reportlab", "requests"):
    try:
        datas += copy_metadata(pkg)
    except Exception:
        pass

# 项目内模块（显式声明，防动态导入漏检）
LOCAL_MODULES = [
    "auth", "browser_runtime", "config", "crawler", "db", "delivery",
    "form_filler", "grab_login", "greeting", "jobstore", "logging_setup",
    "login_status", "loop", "main", "mock_site", "platforms", "resume_ai",
    "resume_pdf", "resume_store", "runtime_paths", "schema", "session",
    "setup_env",
]
hiddenimports += LOCAL_MODULES

a = Analysis(
    ["client.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "secrets_local",  # 密钥不入包（公开仓库+公开 Release）
        "tests", "pytest", "matplotlib",
        # 不拖 Qt 绑定（分析 Qt DLL 极慢且无用）
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        # 深度学习/科学计算重包无引用
        "torch", "torchaudio", "torchvision", "transformers",
        "sentence_transformers", "numba", "llvmlite", "scipy", "sklearn",
        "polars", "cv2",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="智投链客户端",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
