# MyClaw — Agent 工作指南

本文件告诉 AI Agent 如何在这个仓库里工作。

---

## 项目简介

MyClaw 是一个运行在 Windows 本机的个人 AI Agent 执行器。
核心目标：帮用户自动完成任务，同时保持操作可控、可审计。

详细设计见 [docs/design.md](docs/design.md)。

---

## 仓库结构（规划中）

```
my-claw/
├── AGENTS.md              # 本文件
├── docs/
│   └── design.md          # 设计文档
├── backend/               # Python FastAPI 后端（Agent 核心）
│   ├── planner/           # Planner：拆解目标为结构化步骤
│   ├── policy_guard/      # Policy Guard：权限判断与规则管理
│   ├── tool_router/       # Tool Router：调用具体工具
│   ├── memory/            # Memory：SQLite 存规则和历史
│   └── main.py
├── tools/                 # 工具实现
│   ├── filesystem/        # MCP Filesystem
│   ├── browser/           # MCP Browser / Playwright
│   ├── git/               # MCP Git
│   └── shell/             # Shell / PowerShell（高风险兜底）
├── ui/                    # Tauri 桌面端（Rust + React）
└── tests/
```

---

## 核心数据结构

### 操作请求（Planner 输出 → Policy Guard 判断）

```json
{
  "tool": "filesystem",
  "action": "write_file",
  "resource": "D:\\工作\\周报\\week-20.md",
  "params": { "mode": "overwrite" },
  "risk": "medium"
}
```

`risk` 取值：`low` / `medium` / `high`

### 持久规则（存 SQLite，scope 为 always）

```json
{
  "id": "uuid",
  "tool": "filesystem",
  "action": "read_file",
  "resource": "D:\\工作\\周报\\*",
  "effect": "allow",
  "created_at": "2026-05-11T10:00:00+08:00",
  "expires_at": "2026-12-31"
}
```

`effect` 取值：`allow` / `deny`

### 临时授权（存内存，不写 SQLite）

| scope     | 生命周期           |
| --------- | ------------------ |
| `once`    | 本次操作后立即清除 |
| `session` | 进程退出后清除     |

---

## Policy Guard 判断顺序

```
1. 命中持久黑名单（effect: deny）？ → 直接拒绝
2. 命中持久白名单（effect: allow）？ → 自动放行
3. 命中内存临时授权（session/once）？ → 放行，once 用后清除
4. 都没有 → 弹窗让用户决定
```

---

## 开发规范

### 语言与框架
- 后端：Python 3.11+，FastAPI，LangGraph
- 桌面：Rust（Tauri），前端 React
- 存储：SQLite（规则和历史），内存（临时授权）
- 工具协议：MCP

### Policy Guard 是安全核心，修改时必须：
1. 每个改动都有对应单元测试
2. 不得绕过黑名单判断
3. 规则匹配支持通配符（`fnmatch` 风格，如 `D:\工作\*`）

### 工具实现规范
- 每个工具必须声明自己的 `tool` 名称、支持的 `action` 列表、每个 action 的默认 `risk` 等级
- 工具调用前必须经过 Policy Guard，不得直接执行

### 前端状态表达规范
- 当前/选中状态优先用视觉层级表达（边框、底色、强调条、对比度变化），避免用直白中文标签（如“当前”）作为主要识别手段
- 同一页面中，相同语义状态应保持一致的视觉规则，避免交互前后出现“忽隐忽现”的状态误导

### 提交规范
- 提交信息格式：`<scope>: <中文描述>`，例如 `policy_guard: 添加通配符资源匹配`，描述必须用中文
- 不要提交包含真实路径、密钥、个人数据的测试用例

---

## 当前开发阶段

**Step 1**：跑通最小命令行链路（无 UI）

```
用户输入目标
  → Planner 输出结构化操作
  → Policy Guard（终端 y/n，不持久化）
  → 用户输入 y
  → MCP 文件工具执行
  → 打印结果
```

优先在 `backend/` 下实现，不要动 `ui/`。

---

## 不要做的事

- 不要绕过 Policy Guard 直接调用工具
- 不要把临时授权（once/session）写入 SQLite
- 不要在 MVP 阶段引入 UIA/OCR、Windows Sandbox、ChromaDB
- 不要为了"通用性"过度抽象，够用就好
