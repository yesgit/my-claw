from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from uuid import uuid4

from backend.agent import ReactAgent
from backend.mcp import MCPClientManager, MCPServerClient, StdIOTransport, load_mcp_server_configs
from backend.llm import OpenAICompatibleChatClient, OpenAICompatibleConfig
from backend.memory.rule_store import RuleStore
from backend.policy_guard.guard import PolicyGuard
from backend.policy_guard.rules import PolicyRule
from backend.tool_router.router import ToolRouter


def run_react_once(
    client,
    rule_store: RuleStore | None = None,
    mcp_manager: MCPClientManager | None = None,
    max_steps: int = 8,
    filesystem_allowed_dirs: list[str] | None = None,
) -> None:
    guard = PolicyGuard(rule_store=rule_store)
    router = ToolRouter(mcp_manager=mcp_manager, filesystem_allowed_dirs=filesystem_allowed_dirs)
    agent = ReactAgent(client=client, guard=guard, router=router, max_steps=max_steps)

    goal = input("请输入你的目标（ReAct 多轮执行）: ").strip()
    try:
        result = agent.run(goal)
    except ValueError as exc:
        print(f"[ReAct] 解析失败: {exc}")
        return

    print("\n[ReAct] 执行轨迹：")
    print(json.dumps(result.steps, ensure_ascii=False, indent=2))
    print("\n[ReAct] 最终输出：")
    print(json.dumps({"status": result.status, "final_answer": result.final_answer}, ensure_ascii=False, indent=2))


def list_rules(rule_store: RuleStore) -> None:
    rules = rule_store.list_rules()
    if not rules:
        print("[Rules] 当前没有持久规则")
        return

    print("[Rules] 持久规则列表：")
    for rule in rules:
        print(
            json.dumps(
                {
                    "id": rule.id,
                    "tool": rule.tool,
                    "action": rule.action,
                    "resource": rule.resource,
                    "effect": rule.effect,
                    "created_at": rule.created_at,
                    "expires_at": rule.expires_at,
                },
                ensure_ascii=False,
            )
        )


def delete_rule(rule_store: RuleStore, rule_id: str) -> None:
    if rule_store.delete_rule(rule_id):
        print(f"[Rules] 已删除规则: {rule_id}")
    else:
        print(f"[Rules] 规则不存在: {rule_id}")


def add_rule(
    rule_store: RuleStore,
    tool: str,
    action: str,
    resource: str,
    effect: str,
    expires_at: str | None,
) -> None:
    if effect not in {"allow", "deny"}:
        print("[Rules] effect 仅支持 allow 或 deny")
        return

    if expires_at:
        try:
            datetime.fromisoformat(expires_at)
        except ValueError:
            print("[Rules] expires_at 必须是 ISO 时间格式，例如 2026-12-31T23:59:59")
            return

    rule = PolicyRule(
        id=str(uuid4()),
        tool=tool,
        action=action,
        resource=resource,
        effect=effect,
        created_at=datetime.now().isoformat(timespec="seconds"),
        expires_at=expires_at,
    )
    rule_store.add_rule(rule)
    print(f"[Rules] 已新增规则: {rule.id}")


def clear_expired_rules(rule_store: RuleStore) -> None:
    deleted = rule_store.clear_expired_rules()
    print(f"[Rules] 已清理过期规则数量: {deleted}")


def build_mcp_manager(config_path: str | None) -> MCPClientManager:
    manager = MCPClientManager()
    if not config_path:
        return manager

    for server_config in load_mcp_server_configs(config_path):
        transport = StdIOTransport(
            command=server_config.command,
            cwd=server_config.cwd,
            env=server_config.env,
        )
        client = MCPServerClient(server_name=server_config.name, transport=transport)
        client.initialize()
        manager.register_server(client)
    return manager


def list_mcp_servers(manager: MCPClientManager) -> None:
    servers = manager.list_servers()
    if not servers:
        print("[MCP] 当前没有已注册 server")
        return
    print("[MCP] 已注册 server：")
    for server_name in servers:
        print(f"- {server_name}")


def list_mcp_tools(manager: MCPClientManager, server_name: str) -> None:
    tools = manager.list_tools(server_name)
    if not tools:
        print(f"[MCP] server {server_name} 没有返回 tools")
        return
    print(f"[MCP] server {server_name} 工具列表：")
    for tool in tools:
        print(json.dumps(tool, ensure_ascii=False))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MyClaw backend CLI")
    parser.add_argument("--db-path", default=None, help="规则数据库路径")
    parser.add_argument("--mcp-config", default=None, help="MCP server 配置文件路径")
    parser.add_argument("--max-steps", type=int, default=8, help="ReAct 最大执行步数")
    parser.add_argument("--llm-base-url", default=None, help="OpenAI-compatible API base_url")
    parser.add_argument("--llm-api-key", default=None, help="OpenAI-compatible API key")
    parser.add_argument("--llm-model", default=None, help="LLM 模型名")
    parser.add_argument("--llm-timeout", type=float, default=None, help="LLM 请求超时秒数")
    parser.add_argument("--list-rules", action="store_true", help="列出持久规则")
    parser.add_argument("--delete-rule", default=None, help="按规则 id 删除持久规则")
    parser.add_argument("--add-rule", action="store_true", help="新增持久规则")
    parser.add_argument("--rule-tool", default=None, help="规则 tool，例如 filesystem")
    parser.add_argument("--rule-action", default=None, help="规则 action，例如 write_file")
    parser.add_argument("--rule-resource", default=None, help="规则 resource，支持通配符")
    parser.add_argument("--rule-effect", default=None, help="规则 effect：allow 或 deny")
    parser.add_argument("--rule-expires-at", default=None, help="规则过期时间，ISO 格式")
    parser.add_argument("--clear-expired-rules", action="store_true", help="清理已过期规则")
    parser.add_argument("--list-mcp-servers", action="store_true", help="列出已配置 MCP server")
    parser.add_argument("--list-mcp-tools", action="store_true", help="列出指定 MCP server 的工具")
    parser.add_argument("--mcp-server", default=None, help="MCP server 名称")
    parser.add_argument(
        "--filesystem-allowed-dirs",
        nargs="*",
        default=None,
        help="文件系统工具允许操作的目录列表（空格分隔），不设置则不限制",
    )
    return parser


def build_llm_client(args: argparse.Namespace) -> OpenAICompatibleChatClient:
    base_url = args.llm_base_url or os.getenv("MYCLAW_LLM_BASE_URL")
    api_key = args.llm_api_key or os.getenv("MYCLAW_LLM_API_KEY")
    model = args.llm_model or os.getenv("MYCLAW_LLM_MODEL")
    timeout = args.llm_timeout or float(os.getenv("MYCLAW_LLM_TIMEOUT", "60"))

    missing = [name for name, value in {"--llm-base-url": base_url, "--llm-api-key": api_key, "--llm-model": model}.items() if not value]
    if missing:
        raise ValueError(f"需要提供: {', '.join(missing)}")

    return OpenAICompatibleChatClient(
        OpenAICompatibleConfig(base_url=base_url, api_key=api_key, model=model, timeout=timeout)
    )


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    rule_store = RuleStore(db_path=args.db_path)
    mcp_manager = build_mcp_manager(args.mcp_config)
    try:
        if args.list_rules:
            list_rules(rule_store)
            return

        if args.delete_rule:
            delete_rule(rule_store, args.delete_rule)
            return

        if args.add_rule:
            missing = [
                name
                for name, value in {
                    "--rule-tool": args.rule_tool,
                    "--rule-action": args.rule_action,
                    "--rule-resource": args.rule_resource,
                    "--rule-effect": args.rule_effect,
                }.items()
                if not value
            ]
            if missing:
                print(f"[Rules] 缺少参数: {', '.join(missing)}")
                return

            add_rule(
                rule_store=rule_store,
                tool=args.rule_tool,
                action=args.rule_action,
                resource=args.rule_resource,
                effect=args.rule_effect,
                expires_at=args.rule_expires_at,
            )
            return

        if args.clear_expired_rules:
            clear_expired_rules(rule_store)
            return

        if args.list_mcp_servers:
            list_mcp_servers(mcp_manager)
            return

        if args.list_mcp_tools:
            if not args.mcp_server:
                print("[MCP] --list-mcp-tools 需要同时提供 --mcp-server")
                return
            list_mcp_tools(mcp_manager, args.mcp_server)
            return

        # 默认：ReAct 模式
        try:
            client = build_llm_client(args)
        except ValueError as exc:
            print(f"[ReAct] {exc}")
            return
        run_react_once(
            client=client,
            rule_store=rule_store,
            mcp_manager=mcp_manager,
            max_steps=max(1, args.max_steps),
            filesystem_allowed_dirs=args.filesystem_allowed_dirs,
        )
    finally:
        mcp_manager.close_all()


if __name__ == "__main__":
    main()
