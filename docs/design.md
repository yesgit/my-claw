# MyClaw — 个人电脑 Agent 执行器 设计文档

> 版本：v0.1
> 日期：2026-05-11

---

## 1. 产品定位

**在本机帮你自动完成任务，同时让你始终知道它在做什么、始终可以叫停。**

核心三件事：
1. **执行任务**：浏览器操作、文件处理、脚本运行
2. **权限审批**：每个敏感操作都要你点头
3. **记住规则**：你审批过的，下次自动放行

---

## 2. 架构（够用版）

```
桌面 UI（Tauri）
    │  聊天 / 审批弹窗 / 任务日志
    │
Agent 后端（Python FastAPI）
    ├─ Planner        — 把目标拆成步骤，每步直接输出结构化操作
    ├─ Policy Guard   — 每步操作先问要不要允许
    ├─ Tool Router    — 调具体工具
    └─ Memory         — SQLite 存规则和历史

工具
    ├─ MCP Filesystem（文件读写）
    ├─ MCP Browser / Playwright（浏览器）
    ├─ MCP Git（状态、差异、提交）
    └─ Shell / PowerShell（高风险兜底）
```

沙盒和桌面感知（UIA/OCR）是后期选项，MVP 不需要。

---

## 3. 唯一需要想清楚的模块：Policy Guard

```
来了一个结构化操作请求
  → 命中黑名单？      → 直接拒绝
  → 命中白名单/规则？ → 自动放行
  → 都没有？          → 弹窗让用户决定
       用户选：
         允许一次
         在当前会话中允许
         以后对这个路径/网址自动允许（写入规则）
         始终拒绝
```

Planner 每步直接输出结构化操作，格式如下，Policy Guard 据此判断是否放行：

```json
{
  "tool": "filesystem",
  "action": "write_file",
  "resource": "D:\\工作\\周报\\week-20.md",
  "params": {
    "mode": "overwrite"
  },
  "risk": "medium"
}
```

规则字段先保持简单，但要能支持后续审计：

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

---

## 4. 技术栈

| 用途       | 选型                    |
| ---------- | ----------------------- |
| 桌面壳     | Tauri（Rust + React）   |
| 后端       | Python FastAPI          |
| Agent 编排 | LangGraph               |
| 工具协议   | MCP                     |
| 浏览器     | MCP Browser / Playwright |
| 本地存储   | SQLite                  |
| UI ↔ 后端  | Tauri sidecar 启动 FastAPI，WebView 通过 localhost HTTP 通信 |

---

## 5. 开发计划

### Step 1：跑通最小链路（1-2 周）

目标：命令行里能跑通下面这条链路，不需要 UI。

```
用户输入目标
  → Planner 拆步骤，输出结构化操作
  → Policy Guard（最简版：终端 y/n，不持久化）
  → 用户输入 y
  → MCP 文件工具执行
  → 打印结果
```

交付物：能跑的 Python 脚本，无 UI。

---

### Step 2：Policy Guard 完整逻辑（1 周）

在 Step 1 最简版基础上完善：
- 黑/白名单匹配
- 规则持久化到 SQLite（含 `id`、`expires_at`）
- 支持 `scope`：`once`（仅本次）/ `session`（当前会话有效，重启清除，存内存）/ `always`（写入持久规则到 SQLite）
- 支持通配符资源匹配（`D:\工作\*`）
- 规则过期检查

交付物：`policy_guard.py`，有单元测试。

---

### Step 3：接入真实工具（1 周）

按顺序，做一个、稳一个：
1. MCP Filesystem：文件读写、目录列表
2. MCP Browser / Playwright：浏览器操作
3. MCP Git：状态、差异、提交
4. Shell 命令执行（高风险兜底，默认每次审批）

每个工具都走 Policy Guard。

---

### Step 4：桌面 UI（1-2 周）

- Tauri 窗口
- 聊天输入框 + 任务结果展示
- 审批弹窗替代终端 `y/n`
- 规则列表页

---

### Step 5：之后按需加

- 定时任务（内置 Cron，够用就行）
- MCP 插件支持
- Windows Sandbox（真的需要跑高风险代码时再做）
- UIA / OCR 桌面感知（需要操作企业微信时再做）

---

## 6. 不做什么（避免过度设计）

- ~~多用户 / 多 Agent 协作~~
- ~~Hyper-V VM 沙盒~~（先用进程隔离够了）
- ~~ChromaDB 向量记忆~~（SQLite 先扛着）
- ~~任务回放~~（日志够用）
- ~~UIA/OCR~~（MVP 不依赖）
