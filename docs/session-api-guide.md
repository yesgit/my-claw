# MyClaw 会话级任务管理 API 指南

## 概述

会话（Session）是 MyClaw 新增的一级概念。一个会话代表一个独立的运行环境，包含：
- 统一的 LLM 模型配置
- 统一的 MCP 工具配置  
- 统一的文件系统权限
- 多个任务（Task）的集合

在同一会话内发起的任务复用会话的配置，无需每次重复指定。

---

## API 端点

### 会话管理

#### 1. 创建会话
```
POST /api/sessions
Content-Type: application/json

{
  "name": "数据处理会话",
  "config": {
    "providerId": "openai-local",
    "modelId": "gpt-4.1-mini",
    "llmBaseUrl": "http://localhost:8000/v1",
    "llmModel": "gpt-4.1-mini",
    "llmTimeout": 60.0,
    "maxSteps": 8,
    "mcpConfig": "data/mcp_config.json",
    "filesystemAllowedDirs": ["/home/user/documents"],
    "jsonMode": true
  }
}

Response:
{
  "ok": true,
  "session": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "数据处理会话",
    "config": { ... },
    "created_at": "2026-05-12T10:00:00",
    "updated_at": "2026-05-12T10:00:00"
  }
}
```

#### 2. 列出所有会话
```
GET /api/sessions?limit=20&offset=0

Response:
{
  "ok": true,
  "sessions": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "name": "数据处理会话",
      "config": { ... },
      "created_at": "2026-05-12T10:00:00",
      "updated_at": "2026-05-12T10:00:00",
      "task_count": 3
    },
    ...
  ]
}
```

#### 3. 获取会话详情
```
GET /api/sessions/{session_id}

Response:
{
  "ok": true,
  "session": { ... }
}
```

#### 4. 更新会话配置
```
PUT /api/sessions/{session_id}
Content-Type: application/json

{
  "name": "数据处理会话 v2",
  "config": {
    "maxSteps": 10,
    ...
  }
}

Response:
{
  "ok": true,
  "session": { ... }
}
```

#### 5. 删除会话（级联删除所有任务）
```
DELETE /api/sessions/{session_id}

Response:
{
  "ok": true,
  "message": "已删除"
}
```

---

### 任务管理

#### 1. 在会话内发起任务（流式）
```
POST /api/sessions/{session_id}/tasks
Content-Type: application/json

{
  "goal": "读取 /home/user/documents/data.csv，计算平均值",
  "approvalDecision": null  // 可选：预设审批决策 ("y", "1", "2", "3", "4")
}

Response: NDJSON 流（Content-Type: application/x-ndjson）
{"type":"run_boot","goal":"...","run_id":"...","task_id":"...","session_id":"..."}
{"type":"step_start","step":1,"operation":{...}}
{"type":"approval_required","approval_id":"...","operation":{...}}
{"type":"action_result","observation":"..."}
{"type":"step_complete",...}
{"type":"run_complete","status":"completed","final_answer":"..."}
```

#### 2. 列出会话内的所有任务
```
GET /api/sessions/{session_id}/tasks?limit=20&offset=0

Response:
{
  "ok": true,
  "tasks": [
    {
      "id": "task-uuid",
      "session_id": "session-uuid",
      "goal": "读取数据并计算",
      "status": "completed",
      "final_answer": "平均值为 42.5",
      "steps": [ {...}, {...} ],
      "duration_ms": 3500,
      "created_at": "2026-05-12T10:05:00"
    },
    ...
  ]
}
```

#### 3. 获取单个任务详情
```
GET /api/sessions/{session_id}/tasks/{task_id}

Response:
{
  "ok": true,
  "task": { ... }
}
```

---

## 使用流程示例

### 场景：数据处理工作流

#### Step 1: 创建会话
```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "name": "周报生成",
    "config": {
      "providerId": "openai-local",
      "modelId": "gpt-4.1-mini",
      "maxSteps": 8,
      "filesystemAllowedDirs": ["/home/user/documents", "/home/user/reports"]
    }
  }'
```

返回：
```json
{
  "ok": true,
  "session": {
    "id": "session-123",
    ...
  }
}
```

#### Step 2: 在会话内发起第一个任务
```bash
curl -X POST http://localhost:8000/api/sessions/session-123/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "读取 /home/user/documents/work-log.md，总结本周完成的任务"
  }'
```

#### Step 3: 发起第二个任务（复用会话配置）
```bash
curl -X POST http://localhost:8000/api/sessions/session-123/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "根据总结内容，生成周报 Markdown 文件到 /home/user/reports/"
  }'
```

#### Step 4: 查询会话的所有任务
```bash
curl http://localhost:8000/api/sessions/session-123/tasks
```

---

## 与旧 API 的兼容性

`POST /api/run-react` 仍然可用，用于单次执行任务。会话 API 是对其的扩展，用于需要**多个相关任务**在同一配置下运行的场景。

| 特性 | run-react | Session API |
|------|-----------|-------------|
| 单次执行 | ✅ | ✅ |
| 多个任务 | ❌ | ✅ |
| 配置复用 | ❌ | ✅ |
| 会话历史 | ❌ | ✅ |
| 任务隔离 | ❌ | ✅ |

---

## 数据存储

- 所有会话和任务数据存储在 SQLite 数据库 `data/conversations.db`
- 会话配置以 JSON 格式存储
- 任务执行步骤保存为 JSON 数组
- 任务状态：`running` → `completed` / `error` / `max_steps_reached`

---

## 错误处理

所有 API 错误返回标准 HTTP 状态码：
- `200`: 成功
- `400`: 请求参数无效
- `404`: 资源不存在（会话或任务不存在）
- `500`: 服务器内部错误

---

## 安全考虑

1. **Policy Guard** 仍然对所有任务操作适用
2. 任务执行时继承会话的审批规则
3. 文件系统访问受 `filesystemAllowedDirs` 限制
4. 所有操作都被记录到数据库，支持审计
