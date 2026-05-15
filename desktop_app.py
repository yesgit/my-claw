"""
MyClaw 桌面应用入口

后台启动 FastAPI 服务，前台用 pywebview 打开原生桌面窗口。
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# ---- 路径常量 ----
# PyInstaller 打包后 sys._MEIPASS 指向临时解压目录（含代码和静态资源）
# 可执行文件所在目录用于存放用户数据（data/）
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    BUNDLE_DIR = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    EXE_DIR = Path(sys.executable).resolve().parent
else:
    BUNDLE_DIR = Path(__file__).resolve().parent
    EXE_DIR = Path(__file__).resolve().parent

# 数据目录（始终在 exe 旁边）
DATA_DIR = EXE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 日志文件
LOG_FILE = EXE_DIR / "myclaw.log"

# 默认后端端口
DEFAULT_PORT = 21888


def _setup_logging() -> logging.Logger:
    """配置日志：同时输出到文件和控制台"""
    logger = logging.getLogger("myclaw.desktop")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # 文件日志
    try:
        fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    # 控制台日志（开发模式）
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def _crash_log(exc: BaseException) -> None:
    """将崩溃信息写入日志文件和弹窗"""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    msg = "".join(tb)
    try:
        LOG_FILE.write_text(msg, encoding="utf-8")
    except Exception:
        pass

    # 尝试弹窗显示错误
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0,
            f"MyClaw 启动失败:\n\n{exc}\n\n详细信息见:\n{LOG_FILE}",
            "MyClaw 错误",
            0x10,  # MB_ICONERROR
        )
    except Exception:
        pass


def start_backend(port: int) -> None:
    """在子线程中启动 FastAPI 后端"""
    import uvicorn

    # 注入环境变量，让 webapp 知道运行在打包模式
    os.environ["MYCLAW_BUNDLE_DIR"] = str(BUNDLE_DIR)
    os.environ["MYCLAW_DATA_DIR"] = str(DATA_DIR)
    os.environ["MYCLAW_EXE_DIR"] = str(EXE_DIR)

    from backend.webapp import app

    logger.info("启动后端服务，端口: %d", port)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )


def wait_for_backend(url: str, timeout: float = 20.0) -> bool:
    """等待后端就绪"""
    import urllib.request
    import urllib.error

    start = time.time()
    while time.time() - start < timeout:
        try:
            req = urllib.request.Request(url + "/api/health")
            with urllib.request.urlopen(req, timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def main() -> None:
    # 设置工作目录为 exe 所在目录，确保 data/ 等路径正确
    os.chdir(str(EXE_DIR))

    logger.info("=" * 50)
    logger.info("MyClaw 启动中...")
    logger.info("EXE_DIR: %s", EXE_DIR)
    logger.info("BUNDLE_DIR: %s", BUNDLE_DIR)
    logger.info("DATA_DIR: %s", DATA_DIR)
    logger.info("LOG_FILE: %s", LOG_FILE)

    port = int(os.getenv("MYCLAW_PORT", str(DEFAULT_PORT)))
    base_url = f"http://127.0.0.1:{port}"

    # 启动后端线程（daemon 模式，主线程退出时自动结束）
    backend_thread = threading.Thread(
        target=start_backend,
        args=(port,),
        daemon=True,
    )
    backend_thread.start()

    # 等待后端就绪
    logger.info("等待后端服务就绪...")
    if not wait_for_backend(base_url, timeout=20.0):
        logger.error("后端服务启动超时，请检查日志: %s", LOG_FILE)
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"后端服务启动超时。\n\n请查看日志:\n{LOG_FILE}",
                "MyClaw 启动失败",
                0x10,
            )
        except Exception:
            pass
        sys.exit(1)

    logger.info("后端服务已就绪: %s", base_url)

    # 启动 pywebview 桌面窗口
    import webview

    logger.info("启动桌面窗口...")

    window = webview.create_window(
        title="MyClaw Agent Desk",
        url=base_url,
        width=1280,
        height=820,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    # webview.start 会阻塞直到窗口关闭
    webview.start(debug=bool(os.getenv("MYCLAW_DEBUG")))

    logger.info("窗口已关闭，退出应用")
    sys.exit(0)


# 初始化日志
logger = _setup_logging()

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("MyClaw 启动失败")
        _crash_log(exc)
        sys.exit(1)