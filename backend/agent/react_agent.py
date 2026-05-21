from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from backend.models import OperationRequest

logger = logging.getLogger(__name__)


class ReactLLMClient(Protocol):
    def chat(self, messages: list[dict[str, Any]], temperature: float = 0.0) -> str:
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
    max_steps: int = 50
    event_callback: Callable[[dict[str, Any]], None] | None = None

    def _emit(self, event_type: str, **payload: Any) -> None:
        if self.event_callback is None:
            return
        event = {"type": event_type, **payload}
        self.event_callback(event)

    def run(self, goal: str, images: list[dict[str, str]] | None = None) -> ReactAgentResult:
        goal = goal.strip()
        if not goal:
            raise ValueError("目标不能为空")

        self._emit("run_start", goal=goal)

        # 构建用户消息：如果有图片则使用多模态格式
        user_content: str | list[dict[str, Any]]
        if images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": goal}]
            for img in images:
                parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.get('mime_type', 'image/jpeg')};base64,{img['data']}"},
                })
            user_content = parts
        else:
            user_content = goal

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": user_content},
        ]
        steps: list[dict[str, Any]] = []

        for index in range(1, self.max_steps + 1):
            self._emit("step_start", step=index)
            self._emit("llm_pending", step=index)

            # ---- LLM 调用 + 解析，带异常捕获 ----
            try:
                response_text = self.client.chat(messages, temperature=0.0)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Step %d LLM 调用失败", index)
                error_msg = f"LLM 调用失败: {exc}"
                result = ReactAgentResult(status="error", final_answer=error_msg, steps=steps)
                self._emit("run_error", step=index, message=error_msg)
                self._emit(
                    "run_complete",
                    status=result.status,
                    final_answer=result.final_answer,
                    steps=result.steps,
                )
                return result

            self._emit("llm_response", step=index, content=response_text)

            try:
                decision = self._parse_decision(response_text)
            except ValueError as exc:
                logger.warning("Step %d LLM 输出解析失败: %s", index, exc)
                # 解析失败时把错误信息作为 observation 反馈给 LLM，让它再试一次
                error_msg = f"LLM 输出解析失败（第 {index} 步）: {exc}"
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"observation:\n{{\"ok\": false, \"error\": \"{error_msg}\"}}"})
                self._emit("step_complete", step=index, step_record={"step": index, "error": error_msg})
                steps.append({"step": index, "error": error_msg})
                continue

            if decision["type"] == "final":
                result = ReactAgentResult(status="completed", final_answer=decision["final_answer"], steps=steps)
                self._emit(
                    "run_complete",
                    status=result.status,
                    final_answer=result.final_answer,
                    steps=result.steps,
                )
                return result

            if decision["type"] == "cannot_complete":
                reason = decision["reason"]
                result = ReactAgentResult(status="cannot_complete", final_answer=reason, steps=steps)
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

        import platform
        os_name = platform.system()  # Darwin / Windows / Linux
        os_hint = (
            f"当前操作系统: {os_name}"
            + ("（macOS）" if os_name == "Darwin" else "")
            + "\n- shell 命令必须匹配当前操作系统（macOS 用 brew/ps/sed，Windows 用 tasklist/powershell）。"
            + "\n- 当 computer 工具（截图、控件操作等）报错时，禁止用 shell.run_command 调用 python 脚本绕过。"
            "shell 中的 python 环境与 MyClaw 后端不同，pywin32/Pillow 等依赖不一定可用。"
            "遇到 computer 工具错误应直接将错误信息报告给用户。"
        )
        if os_name == "Darwin":
            os_hint += (
                "\n- macOS 常见应用进程名（find_window 的 class_name 填进程名）："
                " 企业微信=WeCom, 微信=WeChat, 钉钉=DingTalk, 飞书=Lark, Safari, Chrome, Finder, 访达=Finder。"
                "\n- find_window 使用策略：**先用 class_name 查找应用所有窗口（不传 title）**，"
                "从返回结果中找到目标窗口的 window_id，再用于后续操作。"
                " 不要同时传 class_name 和 title，因为窗口标题可能不匹配。"
                "\n- 如果不确定进程名，先用 shell.run_command 运行 `ps aux | grep -i 关键词` 查找。"
            )

        return (
            "你是一个 ReAct 执行代理。你每次只能输出一个 JSON 对象，且不能包含任何额外文本。"
            "\n" + os_hint
            + "\n输出格式二选一："
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
            "\n- computer.find_window（查找桌面窗口；params: {class_name?:string, title?:string}）"
            "\n- computer.take_screenshot（截图；params: {hwnd?:int, region?:[int,int,int,int]}，返回 base64 图片）"
            "\n- computer.list_controls（列出窗口控件树；params: {hwnd:int, control_type?:string, name?:string, depth?:int}）"
            "\n- computer.read_text（读取控件文本；params: {hwnd:int, control_type?:string, name?:string, count?:int}）"
            "\n- computer.read_list_items（读取列表子项；params: {hwnd:int, list_name?:string, count?:int}）"
            "\n- computer.click（点击；params: {hwnd:int, x?:int, y?:int, control_type?:string, name?:string}）"
            "\n- computer.type_text（输入文本；params: {text:string, use_clipboard?:bool=true, hwnd?:int, clear_first?:bool}）"
            "\n- computer.send_keys（快捷键；params: {keys:string}，如 {Enter}, {Ctrl}a）"
            "\n- computer.scroll（滚动；params: {hwnd:int, direction?:string, times?:int}）"
            "\n- knowledge.search（搜索知识库；params: {query:string, top_k?:int}）"
            "\n- knowledge.add_text（添加文本到知识库；params: {title:string, content:string, tags?:string[]}）"
            "\n- knowledge.list_docs（列出知识库文档；params: {limit?:int, offset?:int}）"
            "\n- knowledge.get_doc（获取文档详情；resource 为文档 ID）"
            "\n- knowledge.delete_doc（删除文档；resource 为文档 ID，risk 为 high）"
            + scheduler_lines
            + "\n兼容旧格式："
            '{"type":"action","operation":{"tool":"filesystem|shell|mcp","action":"...","resource":"...","params":{},"risk":"low|medium|high"}}'
            "\n2) 任务完成，结束并回答："
            '{"type":"final","final_answer":"..."}'
            "\n3) 暂时无法完成任务："
            '{"type":"cannot_complete","reason":"无法完成的具体原因"}'
            "\n规则："
            "\n- 只输出 JSON，不要代码块。"
            "\n- 如果上一步 observation 显示错误或拒绝，必须根据 observation 调整下一步。"
            "\n- mcp 工具 resource 必须是 mcp://server/tool。"
            "\n- shell 工具 risk 必须为 high，每次执行都需要用户审批。"
            "\n- 需要运行多行脚本时，先用 filesystem.write_file 写入 .py/.sh 文件，再用 shell.run_command 执行该文件。"
            "禁止在 shell.run_command 的 command 参数中内联多行 Python/Shell 脚本，以避免 JSON 转义错误。"
            "\n- 如果你发现经过多次尝试仍无法取得进展（如连续遇到相同错误、缺少必要信息、工具无法满足需求、用户目标不明确），"
            "应主动输出 cannot_complete 结束任务，在 reason 中说明具体原因。不要无意义地重复失败操作。"
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

        if decision_type == "cannot_complete":
            reason = payload.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError("cannot_complete 输出缺少有效 reason")
            return {"type": "cannot_complete", "reason": reason}

        if decision_type == "action_batch":
            operations = self._parse_action_batch(payload)
            return {"type": "action_batch", "operations": operations}

        raise ValueError("LLM 输出 type 必须是 action、action_batch、final 或 cannot_complete")

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
        if tool not in {"filesystem", "shell", "mcp", "scheduler", "computer", "knowledge"}:
            raise ValueError("function_call 工具仅支持 filesystem、shell、mcp、scheduler、computer 或 knowledge")

        resource = arguments.get("resource")
        params = arguments.get("params", {})
        risk = arguments.get("risk", "medium")

        # scheduler、computer、shell、knowledge 工具不需要 resource，默认用 action 名称占位
        if tool in ("scheduler", "computer", "shell", "knowledge"):
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

        if not isinstance(tool, str) or tool not in {"filesystem", "shell", "mcp", "scheduler", "computer", "knowledge"}:
            raise ValueError("operation.tool 必须是 filesystem、shell、mcp、scheduler、computer 或 knowledge")
        if not isinstance(action, str) or not action.strip():
            raise ValueError("operation.action 必须是非空字符串")
        # scheduler、computer、shell、knowledge 不要求 resource 有实质含义，允许空字符串并补为 action 名称
        if tool in ("scheduler", "computer", "shell", "knowledge"):
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

    # observation 文本最大字符数，防止 LLM 上下文爆炸
    _MAX_OBSERVATION_CHARS = 6000

    def _observation_text(self, observation: dict[str, Any]) -> str:
        text = json.dumps(observation, ensure_ascii=False)
        if len(text) > self._MAX_OBSERVATION_CHARS:
            text = text[: self._MAX_OBSERVATION_CHARS] + f"\n...（截断，共 {len(text)} 字符）"
        return "observation:\n" + text
