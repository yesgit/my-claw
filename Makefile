# MyClaw Makefile
# 支持 macOS 和 Windows（WSL / MSYS2 / Git Bash）
#
# 常用命令:
#   make install     — 安装依赖
#   make run         — 开发模式运行桌面应用
#   make web         — 纯 Web 模式（浏览器访问）
#   make test        — 运行测试
#   make build       — PyInstaller 打包
#   make clean       — 清理构建产物

SHELL := /bin/bash
.PHONY: install run web test build clean distclean

# 检测操作系统
UNAME_S := $(shell uname -s)

ifeq ($(UNAME_S),Darwin)
	PYTHON   := python3
	VENV_BIN := .venv/bin
	OPEN_CMD := open
else
	PYTHON   := python
	VENV_BIN := .venv/Scripts
	OPEN_CMD := start
endif

VENV_PYTHON := $(VENV_BIN)/python
VENV_PIP    := $(VENV_BIN)/pip

# ---- 依赖 ----

install: $(VENV_PYTHON)
	$(VENV_PIP) install -r requirements.txt

$(VENV_PYTHON):
	$(PYTHON) -m venv .venv

# ---- 运行 ----

run: $(VENV_PYTHON)
	$(VENV_PYTHON) desktop_app.py

web: $(VENV_PYTHON)
	$(VENV_PYTHON) -m uvicorn backend.webapp:app --reload --port 21888

# ---- 测试 ----

test: $(VENV_PYTHON)
	$(VENV_PIP) install pytest 2>/dev/null
	$(VENV_PYTHON) -m pytest tests/ -v --tb=short

test-coverage: $(VENV_PYTHON)
	$(VENV_PIP) install pytest pytest-cov 2>/dev/null
	$(VENV_PYTHON) -m pytest tests/ -v --tb=short --cov=backend --cov-report=term

# ---- 打包 ----

build: $(VENV_PYTHON)
	$(VENV_PYTHON) -m PyInstaller myclaw.spec --noconfirm
	@echo ""
	@echo "============================================"
	@echo " 构建完成！运行方式:"
	@echo "  dist/MyClaw/MyClaw          (onedir 模式)"
	@echo "  open dist/MyClaw.app        (.app 包)"
	@echo "============================================"
	@echo ""
	@echo "提示: build/ 目录是中间产物，请使用 dist/ 下的最终产物。"

# ---- 清理 ----

clean:
	rm -rf build/ dist/ *.spec
	rm -rf __pycache__ */__pycache__ */*/__pycache__
	rm -rf .pytest_cache
	rm -f myclaw.log

distclean: clean
	rm -rf .venv
	rm -rf data/
