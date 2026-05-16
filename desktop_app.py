"""
MyClaw 桌面应用入口

后台启动 FastAPI 服务，前台用 pywebview 打开原生桌面窗口。
启动过程详细写入日志文件（exe 旁边的 myclaw.log）。
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

# 数据目录（放在用户 home 下，跨版本持久化）
DATA_DIR = Path.home() / ".myclaw"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# 日志文件
LOG_FILE = DATA_DIR / "myclaw.log"

# 默认后端端口
DEFAULT_PORT = 21888


def _setup_logging() -> logging.Logger:
    """配置日志：同时输出到文件和控制台"""
    logger = logging.getLogger("myclaw")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # 文件日志（追加模式，每次启动不覆盖历史）
    try:
        fh = logging.FileHandler(str(LOG_FILE), encoding="utf-8", mode="a")
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


# 初始化日志（尽早，后面的代码都能用）
logger = _setup_logging()


def _show_error_dialog(title: str, message: str) -> None:
    """跨平台弹窗显示错误信息"""
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        pass


def _crash_log(exc: BaseException) -> None:
    """将崩溃信息追加写入日志文件并弹窗"""
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    msg = "".join(tb)
    logger.critical("启动崩溃: %s", msg)

    # 弹窗显示错误
    _show_error_dialog(
        "MyClaw 错误",
        f"MyClaw 启动失败:\n\n{exc}\n\n详细信息见:\n{LOG_FILE}",
    )


def start_backend(port: int) -> None:
    """在子线程中启动 FastAPI 后端"""
    logger.info("[backend] 开始初始化后端服务...")

    # 注入环境变量，让 webapp 知道运行在打包模式
    os.environ["MYCLAW_BUNDLE_DIR"] = str(BUNDLE_DIR)
    os.environ["MYCLAW_DATA_DIR"] = str(DATA_DIR)
    os.environ["MYCLAW_EXE_DIR"] = str(EXE_DIR)
    logger.info("[backend] 环境变量已注入:")
    logger.info("[backend]   MYCLAW_BUNDLE_DIR = %s", BUNDLE_DIR)
    logger.info("[backend]   MYCLAW_DATA_DIR = %s", DATA_DIR)
    logger.info("[backend]   MYCLAW_EXE_DIR = %s", EXE_DIR)
    logger.info("[backend]   MYCLAW_FROZEN = %s", FROZEN)

    # 逐步导入，记录每一步
    try:
        logger.info("[backend] 导入 uvicorn...")
        import uvicorn
        logger.info("[backend] uvicorn 导入成功")
    except Exception as e:
        logger.error("[backend] uvicorn 导入失败: %s", e)
        raise

    try:
        logger.info("[backend] 导入 backend.webapp...")
        from backend.webapp import app, STATIC_DIR
        logger.info("[backend] backend.webapp 导入成功")
        logger.info("[backend] STATIC_DIR = %s", STATIC_DIR)
        logger.info("[backend] STATIC_DIR exists = %s", STATIC_DIR.exists())
        if STATIC_DIR.exists():
            files = list(STATIC_DIR.iterdir())
            logger.info("[backend] STATIC_DIR 内文件: %s", [f.name for f in files[:20]])
    except Exception as e:
        logger.error("[backend] backend.webapp 导入失败: %s", e)
        logger.error("[backend] traceback: %s", traceback.format_exc())
        raise

    logger.info("[backend] 启动 uvicorn，端口: %d", port)
    try:
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )
    except Exception as e:
        logger.error("[backend] uvicorn 运行失败: %s", e)
        raise


def wait_for_backend(url: str, timeout: float = 20.0) -> bool:
    """等待后端就绪"""
    import urllib.request
    import urllib.error

    logger.info("[wait] 开始等待后端就绪: %s/api/health (超时 %.0fs)", url, timeout)
    start = time.time()
    attempt = 0
    while time.time() - start < timeout:
        attempt += 1
        try:
            req = urllib.request.Request(url + "/api/health")
            with urllib.request.urlopen(req, timeout=2) as resp:
                status = resp.read().decode()
                logger.info("[wait] 后端已就绪（第 %d 次尝试, %.1fs）: %s", attempt, time.time() - start, status)
                return True
        except (urllib.error.URLError, OSError) as e:
            if attempt <= 3 or attempt % 10 == 0:
                logger.debug("[wait] 第 %d 次尝试失败: %s", attempt, e)
            time.sleep(0.5)
    logger.error("[wait] 等待超时（%.0fs，%d 次尝试）", timeout, attempt)
    return False


def main() -> None:
    # 设置工作目录为 exe 所在目录，确保 data/ 等路径正确
    os.chdir(str(EXE_DIR))

    logger.info("=" * 60)
    logger.info("MyClaw 桌面应用启动")
    logger.info("=" * 60)
    logger.info("系统信息:")
    logger.info("  sys.platform = %s", sys.platform)
    logger.info("  sys.version = %s", sys.version)
    logger.info("  FROZEN = %s", FROZEN)
    logger.info("  EXE_DIR = %s", EXE_DIR)
    logger.info("  BUNDLE_DIR = %s", BUNDLE_DIR)
    logger.info("  DATA_DIR = %s", DATA_DIR)
    logger.info("  LOG_FILE = %s", LOG_FILE)
    logger.info("  cwd = %s", os.getcwd())

    port = int(os.getenv("MYCLAW_PORT", str(DEFAULT_PORT)))
    base_url = f"http://127.0.0.1:{port}"
    logger.info("端口: %d, base_url: %s", port, base_url)

    # 启动后端线程（daemon 模式，主线程退出时自动结束）
    logger.info("启动后端线程...")
    backend_thread = threading.Thread(
        target=start_backend,
        args=(port,),
        daemon=True,
        name="backend",
    )
    backend_thread.start()
    logger.info("后端线程已创建: %s", backend_thread.name)

    # 等待后端就绪
    if not wait_for_backend(base_url, timeout=20.0):
        logger.error("后端服务启动超时，请检查日志: %s", LOG_FILE)
        _show_error_dialog(
            "MyClaw 启动失败",
            f"后端服务启动超时。\n\n请查看日志:\n{LOG_FILE}",
        )
        sys.exit(1)

    logger.info("后端服务已就绪: %s", base_url)

    # 启动 pywebview 桌面窗口
    try:
        logger.info("导入 pywebview...")
        import webview
        logger.info("pywebview 导入成功，版本: %s", getattr(webview, "__version__", "unknown"))
    except Exception as e:
        logger.error("pywebview 导入失败: %s", e)
        _show_error_dialog(
            "MyClaw 启动失败",
            f"pywebview 导入失败:\n\n{e}\n\n请查看日志:\n{LOG_FILE}",
        )
        sys.exit(1)

    logger.info("创建桌面窗口...")

    window = webview.create_window(
        title="MyClaw Agent Desk",
        url=base_url,
        width=1280,
        height=820,
        min_size=(900, 600),
        resizable=True,
        text_select=True,
    )

    debug_mode = bool(os.getenv("MYCLAW_DEBUG"))
    logger.info("启动 pywebview 事件循环（debug=%s）...", debug_mode)

    # webview.start 会阻塞直到窗口关闭
    webview.start(debug=debug_mode)

    logger.info("窗口已关闭，退出应用")
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        _crash_log(exc)
        sys.exit(1)