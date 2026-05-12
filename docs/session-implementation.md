# MyClaw 会话级任务管理改进总结

## 改进背景

根据 OpenClaw 的架构设计，MyClaw 原有的单次任务执行模式（`POST /api/run-react`）不适合**关联性任务场景**。现改进为**会话级管理**，使得：
- 一次配置（模型、MCP、权限）可复用于多个相关任务
- 任务历史与会话绑定，便于审计和回溯
- 减少重复配置的开销

---

## 核心改动

### 1. 数据库扩展

**文件**: `backend/memory/conversation_store.py`

#### 新增表结构

##### `sessions` 表
```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',  -- JSON 格式，存储 LLM/MCP/权限配置
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

##### `tasks` 表
```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    status TEXT NOT NULL,  -- running | completed | error | max_steps_reached
    final_answer TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]',  -- JSON 数组
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
```

#### 关键特性
- 启用外键约束：`PRAGMA foreign_keys = ON`
- 支持级联删除：删除会话时自动删除关联任务
- 内存数据库支持：测试时可使用 `:memory:` 数据库

#### 新增方法
```python
# Session 管理
- create_session(name, config) -> session_id
- get_session(session_id) -> dict | None
- list_sessions(limit, offset) -> list[dict]
- update_session_config(session_id, config) -> bool
- delete_session(session_id) -> bool

# Task 管理  
- create_task(session_id, goal) -> task_id
- save_task(task_id, status, final_answer, steps, duration_ms) -> bool
- get_task(task_id) -> dict | None
- list_tasks(session_id, limit, offset) -> list[dict]
```

---

### 2. API 端点（FastAPI）

**文件**: `backend/webapp.py`

#### 新增 Pydantic 模型
```python
class SessionConfigPayload  # 会话配置
class CreateSessionRequest  # 创建会话请求
class SessionTaskRequest    # 任务请求
```

#### Session CRUD 端点
```
POST   /api/sessions              # 创建会话
GET    /api/sessions              # 列表会话
GET    /api/sessions/{id}         # 获取会话
PUT    /api/sessions/{id}         # 更新会话配置
DELETE /api/sessions/{id}         # 删除会话
```

#### Task 管理端点
```
POST /api/sessions/{id}/tasks           # 在会话内发起任务（流式 NDJSON）
GET  /api/sessions/{id}/tasks           # 列出任务
GET  /api/sessions/{id}/tasks/{task_id} # 获取任务详情
```

#### 任务执行流程
1. 从会话配置恢复 `ReactRunRequest`
2. 创建 Task 记录（status=running）
3. 启动 ReactAgent，复用 Policy Guard + Tool Router
4. 流式返回 NDJSON 事件（run_boot, step_start, approval_required, action_result 等）
5. 任务完成后保存结果（status, final_answer, steps, duration_ms）

---

### 3. 测试覆盖

**文件**: `tests/test_session_management.py`

12 个单元测试，覆盖：
- ✅ 创建、读取、列表、更新、删除会话
- ✅ 创建任务、保存结果、查询任务
- ✅ 会话内任务隔离
- ✅ 级联删除（删除会话 → 删除所有任务）
- ✅ 任务计数

**全部通过**: 12/12 ✓

---

### 4. 文档

#### docs/session-api-guide.md
- API 端点详解
- 请求/响应格式示例
- 使用流程演示
- 与旧 API 兼容性对比

#### examples/session_demo.py
- 可运行的演示脚本
- 展示完整工作流程（创建会话 → 多个任务 → 查询结果）

---

## 设计优势

| 方面 | 单次 run-react | 新增 Session API |
|------|---------------|--------------------|
| **配置复用** | ❌ 每次重复提供 | ✅ 一次配置，多个任务 |
| **会话隔离** | ❌ 无概念 | ✅ 任务与会话绑定 |
| **历史追溯** | ⚠️ 所有任务混在一起 | ✅ 按会话分组 |
| **并发支持** | ✅ 各自独立 | ✅ 会话独立，支持多会话并行 |
| **权限管理** | ⚠️ 每次单独配置 | ✅ 会话级权限一致性 |
| **审计** | ⚠️ 困难 | ✅ 完整的会话+任务链路 |

---

## 向后兼容性

- ✅ 旧的 `POST /api/run-react` 端点保持不变
- ✅ 旧的 `ConversationStore` 方法（对话记录相关）完全保留
- ✅ 新增 sessions/tasks 表与旧 conversations 表并存
- ⚠️ 默认数据库位置不变（`data/conversations.db`）

**迁移建议**：
- 新增功能优先使用 Session API
- 单个一次性任务仍可使用 `run-react`

---

## 实现亮点

### 1. 内存数据库支持
测试中使用 `:memory:` 时，自动保持单一连接实例，避免 SQLite 内存库创建多个独立副本的问题。

### 2. 外键约束启用
每次连接时执行 `PRAGMA foreign_keys = ON`，确保级联删除生效。

### 3. JSON 配置序列化
会话配置以 JSON 形式存储在 SQLite，易于扩展和查询。

### 4. 流式 NDJSON 事件
任务执行时，通过 `application/x-ndjson` 持续输出事件，支持前端实时显示。

---

## 后续工作

### 前端适配（待做）
- [ ] `/sessions` 页面：会话列表与创建
- [ ] `/sessions/{id}` 页面：会话配置与任务历史
- [ ] 任务详情面板：步骤信息和执行日志
- [ ] 会话删除确认对话

### 功能扩展（建议）
- [ ] 会话模板：保存常用配置为模板
- [ ] 任务调度：支持定期重复任务
- [ ] 会话共享：支持会话权限管理
- [ ] 实时协作：多用户同会话操作（需工程量）

---

## 代码统计

| 组件 | 代码行数 | 说明 |
|------|---------|------|
| conversation_store.py | +180 | 新增 Session/Task 管理方法 |
| webapp.py | +230 | 新增 Session API 端点 |
| test_session_management.py | +180 | 12 个单元测试 |
| session-api-guide.md | +220 | API 文档 |
| session_demo.py | +140 | 可运行示例 |
| **合计** | **≈950** | **仅后端改动** |

---

## 验证清单

- ✅ 所有单元测试通过（12/12）
- ✅ 示例脚本可运行
- ✅ 数据库表创建正确
- ✅ 级联删除生效
- ✅ JSON 序列化正确
- ✅ API 文档完整
- ✅ 向后兼容

---

## 使用示例

```python
# 1. 创建会话
store = ConversationStore()
session_id = store.create_session(
    name="数据处理",
    config={
        "providerId": "openai-local",
        "modelId": "gpt-4.1-mini",
        "maxSteps": 8,
    }
)

# 2. 发起任务 (通过 API)
# POST /api/sessions/{session_id}/tasks
# { "goal": "读取并分析数据" }

# 3. 查询结果
tasks = store.list_tasks(session_id)
for task in tasks:
    print(f"{task['goal']} -> {task['final_answer']}")
```

---

## 参考资源

- 设计文档：[docs/design.md](docs/design.md)
- API 指南：[docs/session-api-guide.md](docs/session-api-guide.md)
- 示例代码：[examples/session_demo.py](examples/session_demo.py)
- 测试代码：[tests/test_session_management.py](tests/test_session_management.py)
