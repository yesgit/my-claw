from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from backend.models import OperationRequest


class ReactLLMClient(Protocol):
    def chat(self, messages: list[dict[str, str]], temperature: float = 0.0) -> str:
        ...


class GuardProtocol(Protocol):
    def approve(self, operation: OperationRequest) -> bool:
        ...


class RouterProtocol(Protocol):
    def execute(self, operation: OperationRequest) -> dict[str, Any]:
        ...


@dataclass(slots=True)
class ReactAgentResult:
    status: str
    final_answer: str
    steps: list[dict[str, Any]]


@dataclass(slots=True)
class ReactAgent:
    client: ReactLLMClient
    guard: GuardProtocol
    router: RouterProtocol
    max_steps: int = 8
    event_callback: Callable[[dict[str, Any]], None] | None = None

    def _emit(self, event_type: str, **payload: Any) -> None:
        if self.event_callback is None:
            return
        event = {"type": event_type, **payload}
        self.event_callback(event)

    def run(self, goal: str) -> ReactAgentResult:
        goal = goal.strip()
        if not goal:
            raise ValueError("目标不能为空")

        self._emit("run_start", goal=goal)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": goal},
        ]
        steps: list[dict[str, Any]] = []

        for index in range(1, self.max_steps + 1):
            self._emit("step_start", step=index)
            self._emit("llm_pending", step=index)
            response_text = self.client.chat(messages, temperature=0.0)
            self._emit("llm_response", step=index, content=response_text)
            decision = self._parse_decision(response_text)

            if decision["type"] == "final":
                result = ReactAgentResult(status="completed", final_answer=decision["final_answer"], steps=steps)
                self._emit(
                    "run_complete",
                    status=result.status,
                    final_answer=result.final_answer,
                    steps=result.steps,
                )
                return result

            operation_items: list[dict[str, Any]] = decision["operations"]
            executed_items: list[dict[str, Any]] = []
            for operation_item in operation_items:
                operation = operation_item["operation"]
                tool_call_id = operation_item.get("tool_call_id")
                self._emit(
                    "action_start",
                    step=index,
                    tool_call_id=tool_call_id,
                    operation=operation.to_dict(),
                )
                approved = self.guard.approve(operation)
                self._emit(
                    "approval",
                    step=index,
                    tool_call_id=tool_call_id,
                    approved=approved,
                    operation=operation.to_dict(),
                )
                if not approved:
                    observation = {
                        "ok": False,
                        "error": "rejected_by_policy_guard",
                        "operation": operation.to_dict(),
                    }
                    if tool_call_id:
                        observation["tool_call_id"] = tool_call_id
                    record = {"operation": operation.to_dict(), "observation": observation}
                    if tool_call_id:
                        record["tool_call_id"] = tool_call_id
                    executed_items.append(record)
                    self._emit("action_result", step=index, tool_call_id=tool_call_id, observation=observation)
                    continue

                try:
                    result = self.router.execute(operation)
                    observation = {"ok": True, "result": result}
                except Exception as exc:  # noqa: BLE001
                    observation = {
                        "ok": False,
                        "error": str(exc),
                        "operation": operation.to_dict(),
                    }
                if tool_call_id:
                    observation["tool_call_id"] = tool_call_id

                record = {"operation": operation.to_dict(), "observation": observation}
                if tool_call_id:
                    record["tool_call_id"] = tool_call_id
                executed_items.append(record)
                self._emit("action_result", step=index, tool_call_id=tool_call_id, observation=observation)

            if len(executed_items) == 1:
                step_record = {
                    "step": index,
                    "operation": executed_items[0]["operation"],
                    "observation": executed_items[0]["observation"],
                }
                if executed_items[0].get("tool_call_id"):
                    step_record["tool_call_id"] = executed_items[0]["tool_call_id"]
                observation_for_llm: dict[str, Any] = executed_items[0]["observation"]
            else:
                step_record = {
                    "step": index,
                    "operations": [item["operation"] for item in executed_items],
                    "observations": [item["observation"] for item in executed_items],
                }
                tool_call_ids = [item["tool_call_id"] for item in executed_items if item.get("tool_call_id")]
                if tool_call_ids:
                    step_record["tool_call_ids"] = tool_call_ids
                observation_for_llm = {
                    "ok": all(item["observation"].get("ok", False) for item in executed_items),
                    "batch": [item["observation"] for item in executed_items],
                }

            steps.append(step_record)
            self._emit("step_complete", step=index, step_record=step_record)
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": self._observation_text(observation_for_llm)})

        result = ReactAgentResult(
            status="max_steps_reached",
            final_answer="已达到最大执行步数，未能完成任务。",
            steps=steps,
        )
        self._emit(
            "run_complete",
            status=result.status,
            final_answer=result.final_answer,
            steps=result.steps,
        )
        return result

    def _system_prompt(self) -> str:
        # 检查 router 是否挂载了 scheduler 工具
        scheduler_lines = ""
        try:
            tool_names = {t.get("tool", "") for t in self.router.list_tools()}  # type: ignore[attr-defined]
            if "scheduler" in tool_names:
                scheduler_lines = (
                    "\n- scheduler.create_schedule（创建定时任务；无需 resource；params: {name:string, prompt:string, interval_seconds:int>=30, enabled?:bool}）"
                    "\n- scheduler.list_schedules（列出当前会话定时任务；无需 resource 和 params）"
                    "\n- scheduler.delete_schedule（删除定时任务；params: {schedule_id:string}）"
                    "\n- scheduler.update_schedule（更新定时任务；params: {schedule_id:string, name?, prompt?, interval_seconds?, enabled?}）"
                )
        except Exception:  # noqa: BLE001
            pass

        scheduler_rule = (
            "\n- 当用户要求周期性/定时/自动重复执行任务时，必须优先使用 scheduler.create_schedule 创建定时任务，禁止使用 shell cron 或脚本。"
            if scheduler_lines else ""
        )

        return (
            "你是一个 ReAct 执行代理。你每次只能输出一个 JSON 对象，且不能包含任何额外文本。"
            "\n输出格式二选一："
            "\n1) 继续执行动作（推荐 function_call 形式）："
            '{"type":"action","function_call":{"name":"filesystem.read_file","arguments":{"resource":"/tmp/a.txt","params":{},"risk":"medium"}}}'
            "\n1.1) 批量动作（当模型返回多个 tool_calls 时使用）："
            '{"type":"action_batch","function_calls":[{"name":"filesystem.read_file","arguments":{"resource":"/tmp/a.txt","params":{},"risk":"medium"}}]}'
            "\n可用 function_call.name："
            "\n- filesystem.write_file"
            "\n- filesystem.read_file"
            "\n- filesystem.list_dir"
            "\n- filesystem.copy_file"
            "\n- filesystem.move_file"
            "\n- filesystem.delete_path"
            "\n- shell.run_command（arguments.params.command 为要执行的命令，risk 固定为 high）"
            "\n- mcp.call_tool（arguments.resource 必须是 mcp://server/tool）"
            + scheduler_lines
            + "\n兼容旧格式："
            '{"type":"action","operation":{"tool":"filesystem|shell|mcp","action":"...","resource":"...","params":{},"risk":"low|medium|high"}}'
            "\n2) 结束并回答："
            '{"type":"final","final_answer":"..."}'
            "\n规则："
            "\n- 只输出 JSON，不要代码块。"
            "\n- 如果上一步 observation 显示错误或拒绝，必须根据 observation 调整下一步。"
            "\n- mcp 工具 resource 必须是 mcp://server/tool。"
            "\n- shell 工具 risk 必须为 high，每次执行都需要用户审批。"
            + scheduler_rule
        )

    def _parse_decision(self, content: str) -> dict[str, Any]:
        payload = self._parse_json(content)
        if not isinstance(payload, dict):
            raise ValueError("LLM 输出必须是 JSON 对象")

        decision_type = payload.get("type")
        if decision_type == "final":
            final_answer = payload.get("final_answer")
            if not isinstance(final_answer, str) or not final_answer.strip():
                raise ValueError("final 输出缺少有效 final_answer")
            return {"type": "final", "final_answer": final_answer}

        if decision_type == "action":
            operation_item = self._parse_action(payload)
            return {"type": "action", "operations": [operation_item]}

        if decision_type == "action_batch":
            operations = self._parse_action_batch(payload)
            return {"type": "action_batch", "operations": operations}

        raise ValueError("LLM 输出 type 必须是 action、action_batch 或 final")

    def _parse_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        function_call = payload.get("function_call")
        if function_call is not None:
            return self._parse_function_call(function_call)

        operation_payload = payload.get("operation")
        return {"operation": self._parse_operation(operation_payload), "tool_call_id": None}

    def _parse_action_batch(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        function_calls = payload.get("function_calls")
        if isinstance(function_calls, list):
            if not function_calls:
                raise ValueError("action_batch.function_calls 不能为空")
            return [self._parse_function_call(item) for item in function_calls]

        operations = payload.get("operations")
        if isinstance(operations, list):
            if not operations:
                raise ValueError("action_batch.operations 不能为空")
            return [self._parse_operation(item) for item in operations]

        raise ValueError("action_batch 需要提供 function_calls 或 operations 列表")

    def _parse_function_call(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("action.function_call 必须是 JSON 对象")

        name = payload.get("name")
        arguments = payload.get("arguments", {})
        tool_call_id = payload.get("id")
        if not isinstance(name, str) or "." not in name:
            raise ValueError("function_call.name 必须是 <tool>.<action> 格式")
        if not isinstance(arguments, dict):
            raise ValueError("function_call.arguments 必须是对象")
        if tool_call_id is not None and (not isinstance(tool_call_id, str) or not tool_call_id.strip()):
            raise ValueError("function_call.id 如果提供，必须是非空字符串")

        tool, action = name.split(".", 1)
        if tool not in {"filesystem", "shell", "mcp", "scheduler"}:
            raise ValueError("function_call 工具仅支持 filesystem、shell、mcp 或 scheduler")

        resource = arguments.get("resource")
        params = arguments.get("params", {})
        risk = arguments.get("risk", "medium")

        # scheduler 工具不需要 resource（params 里已包含全部参数），默认用 action 名称占位
        if tool == "scheduler":
            if not isinstance(resource, str) or not resource.strip():
                resource = action
        else:
            if not isinstance(resource, str) or not resource.strip():
                raise ValueError("function_call.arguments.resource 必须是非空字符串")
        if not isinstance(params, dict):
            raise ValueError("function_call.arguments.params 必须是对象")

        operation = self._parse_operation(
            {
                "tool": tool,
                "action": action,
                "resource": resource,
                "params": params,
                "risk": risk,
            }
        )
        return {"operation": operation, "tool_call_id": tool_call_id}

    def _parse_operation(self, payload: Any) -> OperationRequest:
        if not isinstance(payload, dict):
            raise ValueError("action.operation 必须是 JSON 对象")

        allowed_keys = {"tool", "action", "resource", "params", "risk"}
        payload_keys = set(payload.keys())
        if not payload_keys.issubset(allowed_keys):
            extra_keys = sorted(payload_keys - allowed_keys)
            raise ValueError(f"operation 包含不允许的字段：{', '.join(extra_keys)}")

        required_keys = {"tool", "action", "resource"}
        if not required_keys.issubset(payload_keys):
            raise ValueError("operation 缺少必要字段：tool/action/resource")

        tool = payload["tool"]
        action = payload["action"]
        resource = payload["resource"]
        params = payload.get("params", {})
        risk = payload.get("risk", "medium")

        if not isinstance(tool, str) or tool not in {"filesystem", "shell", "mcp", "scheduler"}:
            raise ValueError("operation.tool 必须是 filesystem、shell、mcp 或 scheduler")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("operation.action 必须是非空字符串")
        # scheduler 不要求 resource 有实质含义，允许空字符串并补为 action 名称
        if tool == "scheduler":
            if not isinstance(resource, str) or not resource.strip():
                resource = action
        else:
            if not isinstance(resource, str) or not resource.strip():
                raise ValueError("operation.resource 必须是非空字符串")
        if not isinstance(params, dict):
            raise ValueError("operation.params 必须是对象")
        if not isinstance(risk, str) or risk not in {"low", "medium", "high"}:
            raise ValueError("operation.risk 必须是 low, medium, high 之一")
        if tool == "mcp" and not resource.startswith("mcp://"):
            raise ValueError("当 operation.tool 为 mcp 时，resource 必须是 mcp://server/tool 格式")

        return OperationRequest(tool=tool, action=action, resource=resource, params=params, risk=risk)

    def _parse_json(self, content: str) -> Any:
        content = content.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
        if fenced:
            content = fenced.group(1)

        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            content = content[start : end + 1]

        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM 输出不是有效 JSON: {exc}") from exc

    def _observation_text(self, observation: dict[str, Any]) -> str:
        return "observation:\n" + json.dumps(observation, ensure_ascii=False)
