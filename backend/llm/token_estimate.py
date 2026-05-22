"""轻量 Token 估算工具。

不依赖 tiktoken 等编译库，基于字符数粗估。
中英混合场景经验值：1 token ≈ 3 字符（含 JSON 结构开销）。
"""
from __future__ import annotations

from typing import Any

# 粗估系数：字符数 / 此值 ≈ token 数
_CHARS_PER_TOKEN = 3.0

# 压缩触发阈值（估算 token 数）
DEFAULT_AUTO_COMPRESS_THRESHOLD = 80_000

# 压缩后保留最近 N 条消息（N/2 轮对话）
DEFAULT_COMPRESS_KEEP_RECENT = 6


def estimate_text_tokens(text: str) -> int:
    """估算一段文本的 token 数。"""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """估算 messages 列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            # 多模态消息（text + image_url 等）
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    total += estimate_text_tokens(text)
                    # image_url 的 base64 数据占用大量 token
                    if part.get("type") == "image_url":
                        img_url = part.get("image_url", {}).get("url", "")
                        if img_url and ";base64," in img_url:
                            b64_data = img_url.split(";base64,", 1)[-1]
                            # base64 编码的图片 token 粗估：每 4 个 base64 字符 ≈ 3 字节原始数据
                            # 视觉模型通常按图像分辨率计费，这里用简单估算
                            total += max(100, len(b64_data) // 6)
        # 每条消息有少量结构开销（role、name 等字段）
        total += 4
    return total


def format_token_count(count: int) -> str:
    """格式化 token 数为人类可读字符串。"""
    if count < 1000:
        return str(count)
    if count < 1_000_000:
        return f"{count / 1000:.1f}k"
    return f"{count / 1_000_000:.1f}M"


def compute_context_percent(estimated_tokens: int, max_tokens: int = 128_000) -> int:
    """计算上下文使用百分比。"""
    if max_tokens <= 0:
        return 0
    return min(100, int(estimated_tokens * 100 / max_tokens))


def compress_steps_summary(steps: list[dict[str, Any]]) -> str:
    """将步骤列表压缩为简洁摘要文本（用于替换中间消息）。

    不调用 LLM，纯规则提取。
    """
    if not steps:
        return "（无历史步骤）"

    lines: list[str] = []
    for step in steps:
        step_num = step.get("step", "?")

        # 单操作步骤
        operation = step.get("operation")
        observation = step.get("observation")
        if operation:
            tool = operation.get("tool", "?")
            action = operation.get("action", "?")
            resource = operation.get("resource", "")
            res_display = f'("{resource}")' if resource and resource != action else ""
            status = "✓" if observation and observation.get("ok") else "✗"
            error_hint = ""
            if observation and not observation.get("ok") and observation.get("error"):
                error_hint = f" 错误: {observation['error'][:60]}"
            lines.append(f"  Step {step_num}: {tool}.{action}{res_display} → {status}{error_hint}")
            continue

        # 批量操作步骤
        operations = step.get("operations", [])
        observations = step.get("observations", [])
        if operations:
            for i, op in enumerate(operations):
                tool = op.get("tool", "?")
                action = op.get("action", "?")
                resource = op.get("resource", "")
                res_display = f'("{resource}")' if resource and resource != action else ""
                obs = observations[i] if i < len(observations) else {}
                status = "✓" if obs and obs.get("ok") else "✗"
                lines.append(f"  Step {step_num}#{i + 1}: {tool}.{action}{res_display} → {status}")
            continue

        # 错误步骤
        if step.get("error"):
            lines.append(f"  Step {step_num}: 解析错误 - {step['error'][:80]}")

    summary = f"[历史步骤摘要，共 {len(steps)} 步]\n" + "\n".join(lines)
    # 限制摘要长度，防止摘要本身也过长
    if len(summary) > 3000:
        summary = summary[:3000] + f"\n...（截断，共 {len(steps)} 步）"
    return summary