# MyClaw 桌面应用构建指南

> ⚠️ PyInstaller 不支持交叉编译，**必须在 Windows 上构建 Windows 安装包**。

---

## 前置条件

| 工具 | 版本 | 用途 |
|------|------|------|
| Python | 3.11+ | 运行构建脚本 |
| Inno Setup | 6.x | 生成安装包（可选，也可直接用 zip 分发） |

---

## 快速构建（Windows）

### 1. 克隆项目 & 安装依赖

```powershell
git clone <repo-url> my-claw
cd my-claw

python -m venv .venv
.venv\Scripts\activate

pip install -r requirements.txt
```

### 2. 测试桌面应用（开发模式）

先确认能正常运行：

```powershell
python desktop_app.py
```

会弹出一个桌面窗口，访问 `http://127.0.0.1:21888`。

### 3. PyInstaller 打包

```powershell
pyinstaller myclaw.spec
```

输出目录：`dist/MyClaw/`

### 4. 测试打包结果

```powershell
dist\MyClaw\MyClaw.exe
```

确认能正常启动、打开窗口、功能正常。

### 5. 制作安装包（可选）

安装 [Inno Setup](https://jrsoftware.org/isdl.php)，然后：

```powershell
# 方式一：GUI 编译
# 右键 installer.iss → Compile（Inno Setup 会加入右键菜单）

# 方式二：命令行编译
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

输出文件：`dist/installer/MyClaw-Setup-0.3.0.exe`

---

## 文件结构说明

```
my-claw/
├── desktop_app.py      # 桌面入口：pywebview 窗口 + uvicorn 后端
├── myclaw.spec         # PyInstaller 打包配置
├── installer.iss       # Inno Setup 安装脚本
├── requirements.txt    # Python 依赖
├── backend/            # FastAPI 后端代码（打包时包含）
├── ui/web/             # 静态前端文件（打包时包含）
└── data/               # 运行时数据（数据库、配置，不打包）
```

---

## 运行时行为

1. `MyClaw.exe` 启动后，后台线程启动 FastAPI 服务（端口 21888）
2. 等待后端 `/api/health` 返回 200
3. 用 pywebview 打开系统 WebView2 窗口，加载 `http://127.0.0.1:21888`
4. 用户关闭窗口 → 进程退出，后端随之停止

### 数据存储位置

| 数据 | 路径 |
|------|------|
| SQLite 数据库 | `{exe所在目录}/data/conversations.db` |
| 模型配置 | `{exe所在目录}/data/model_profiles.json` |
| MCP 配置 | `{exe所在目录}/data/mcp_config.json` |

---

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MYCLAW_PORT` | `21888` | 后端监听端口 |
| `MYCLAW_DEBUG` | （空） | 设为 `1` 开启 WebView 开发者工具 |

---

## 常见问题

### Q: 启动后窗口空白？
A: 等待几秒，后端首次启动需要加载。如果持续空白，设置 `MYCLAW_DEBUG=1` 查看控制台。

### Q: 提示缺少 WebView2？
A: Windows 10 (2004+) 和 Windows 11 已内置 WebView2。旧系统需要手动安装：
https://developer.microsoft.com/en-us/microsoft-edge/webview2/

### Q: 打包体积多大？
A: 预计 30-50MB（含 Python 运行时 + 依赖）。UPX 压缩已启用。

### Q: 防火墙弹窗？
A: 这是首次启动时 Windows 检测到监听端口。选择"允许"即可，MyClaw 只监听本机 127.0.0.1，不对外暴露。

---

## 开发者：不用打包直接运行

如果你只是开发调试，不需要打包：

```powershell
# 方式一：纯 Web 模式（浏览器访问）
uvicorn backend.webapp:app --reload --port 21888
# 然后浏览器打开 http://127.0.0.1:21888

# 方式二：桌面窗口模式
python desktop_app.py
```
