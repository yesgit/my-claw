# -*- mode: python ; coding: utf-8 -*-
"""
MyClaw PyInstaller 打包配置

在 Windows 上执行: pyinstaller myclaw.spec
"""

import sys
from pathlib import Path

block_cipher = None

ROOT = Path(SPECPATH)

# 收集所有后端 Python 代码
backend_datas = [
    (str(ROOT / "backend"), "backend"),
    (str(ROOT / "ui" / "web"), str(Path("ui") / "web")),
]

# 确保 data 目录存在（运行时存放数据库和配置）
data_dir = ROOT / "data"

a = Analysis(
    [str(ROOT / "desktop_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=backend_datas,
    hiddenimports=[
        # 后端模块
        "backend",
        "backend.webapp",
        "backend.main",
        "backend.models",
        "backend.agent",
        "backend.agent.react_agent",
        "backend.llm",
        "backend.llm.openai_compatible",
        "backend.mcp",
        "backend.mcp.client",
        "backend.mcp.config",
        "backend.mcp.demo_server",
        "backend.mcp.stdio_transport",
        "backend.memory",
        "backend.memory.rule_store",
        "backend.memory.conversation_store",
        "backend.policy_guard",
        "backend.policy_guard.guard",
        "backend.policy_guard.rules",
        "backend.tool_router",
        "backend.tool_router.router",
        "backend.tools",
        "backend.tools.filesystem",
        "backend.tools.filesystem.tool",
        "backend.tools.shell",
        "backend.tools.shell.tool",
        "backend.tools.scheduler",
        "backend.tools.scheduler.tool",
        "backend.tools.computer",
        "backend.tools.computer.tool",
        "backend.tools.computer.actor",
        "backend.tools.computer.reader",
        "backend.tools.computer.state",
        "backend.tools.computer.window_manager",
        # 依赖
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "fastapi",
        "starlette",
        "starlette.responses",
        "starlette.routing",
        "starlette.middleware",
        "pydantic",
        "pydantic.fields",
        "pydantic.main",
        "httpx",
        "anyio",
        "anyio._backends._asyncio",
        "sniffio",
        # pywebview
        "webview",
        "webview.platforms",
        "webview.platforms.winforms",
        # 标准库
        "sqlite3",
        "json",
        "urllib",
        "urllib.request",
        "urllib.error",
        # dataclass 支持器（slots=True 需要）
        "dataclasses",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "pytest",
    ],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MyClaw",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,       # 不显示命令行窗口
    disable_windowed_traceback=False,
    icon=str(ROOT / "icon.ico") if (ROOT / "icon.ico").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MyClaw",
)