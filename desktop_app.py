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
from pathlib import Path

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("myclaw.desktop")

# 项目根目录
ROOT_DIR = Path(__file__).resolve().parent

# 默认后端端口
DEFAULT_PORT = 21888


def find_free_port() -> int:
    """找一个空闲端口"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_backend(port: int) -> None:
    """在子线程中启动 FastAPI 后端"""
    import uvicorn
    from backend.webapp import app

    logger.info("启动后端服务，端口: %d", port)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )


def wait_for_backend(url: str, timeout: float = 15.0) -> bool:
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
            time.sleep(0.3)
    return False


def main() -> None:
    port = int(os.getenv("MYCLAW_PORT", DEFAULT_PORT))
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
    if not wait_for_backend(base_url, timeout=15.0):
        logger.error("后端服务启动超时，请检查日志")
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


if __name__ == "__main__":
    main()