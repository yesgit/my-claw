from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from typing import Callable
from uuid import uuid4

from backend.memory.conversation_store import ConversationStore
from backend.memory.rule_store import RuleStore
from backend.models import OperationRequest
from backend.policy_guard.rules import PolicyRule

# 风险等级排序，用于 max_risk 比较
_RISK_ORDER = {"low": 0, "medium": 1, "high": 2}


def _risk_lte(actual: str, ceiling: str) -> bool:
    """判断 actual 风险等级是否 <= ceiling。"""
    return _RISK_ORDER.get(actual, 1) <= _RISK_ORDER.get(ceiling, 1)


def _generalize_resource(resource: str, levels: int = 1) -> str:
    """将资源路径向上泛化指定层数，返回 glob 模式。

    例如：
      "D:\\工作\\周报\\week-20.md" levels=1 → "D:\\工作\\周报\\*"
      "D:\\工作\\周报\\week-20.md" levels=2 → "D:\\工作\\*"
    """
    p = Path(resource)
    for _ in range(levels):
        parent = p.parent
        if parent == p:
            break
        p = parent
    return str(p) + "*"


@dataclass(slots=True)
class TempGrant:
    tool: str
    action: str
    resource: str
    scope: str


class PolicyGuard:
    """Policy guard with persistent rules, session rules, and in-memory temp authorization."""

    def __init__(
        self,
        input_func=input,  # noqa: A002
        rule_store: RuleStore | None = None,
        conversation_store: ConversationStore | None = None,
        session_id: str | None = None,
        decision_func: Callable[[OperationRequest, str], str] | None = None,
    ) -> None:
        self._input = input_func
        self._rule_store = rule_store or RuleStore()
        self._conversation_store = conversation_store
        self._session_id = session_id
        self._temp_grants: list[TempGrant] = []
        self._decision_func = decision_func

    def approve(self, operation: OperationRequest) -> bool:
        persistent_rules = self._active_persistent_rules()

        if self._match_effect(persistent_rules, operation, "deny"):
            print("[Policy Guard] 命中持久 deny 规则，已拒绝")
            return False

        if self._match_effect(persistent_rules, operation, "allow"):
            print("[Policy Guard] 命中持久 allow 规则，自动放行")
            return True

        if self._match_session_rules(operation, "deny"):
            print("[Policy Guard] 命中会话 deny 规则，已拒绝")
            return False

        if self._match_session_rules(operation, "allow"):
            print("[Policy Guard] 命中会话 allow 规则，自动放行")
            return True

        if self._match_temp_grant(operation):
            print("[Policy Guard] 命中临时授权，自动放行")
            return True

        print("\n[Policy Guard] 待审批操作：")
        print(operation.to_dict())

        prompt = (
            "请选择：\n"
            "  1) 允许一次 (y)\n"
            "  2) 本会话允许\n"
            "  3) 允许当前文件夹 (*)\n"
            "  4) 允许父目录 (**)\n"
            "  5) 允许该工具所有操作\n"
            "  6) 允许所有中低风险操作\n"
            "  7) 始终允许 (精确路径)\n"
            "  8) 始终拒绝 (n)\n"
            "请输入编号: "
        )
        if self._decision_func is not None:
            answer = self._decision_func(operation, prompt).strip().lower()
        else:
            answer = self._input(prompt).strip().lower()
        return self._handle_user_decision(operation, answer)

    def _active_persistent_rules(self) -> list[PolicyRule]:
        now = datetime.now()
        rules = self._rule_store.list_rules()
        return [rule for rule in rules if not rule.is_expired(now)]

    def _match_effect(
        self,
        rules: list[PolicyRule],
        operation: OperationRequest,
        effect: str,
    ) -> bool:
        for rule in rules:
            if rule.effect != effect:
                continue
            # max_risk 检查：如果规则设了 max_risk，操作的 risk 必须不超过它
            if rule.max_risk is not None and not _risk_lte(operation.risk, rule.max_risk):
                continue
            if self._matches_rule(rule.tool, operation.tool) and self._matches_rule(
                rule.action,
                operation.action,
            ) and fnmatch(operation.resource, rule.resource):
                return True
        return False

    def _matches_rule(self, rule_value: str, actual_value: str) -> bool:
        return rule_value == "*" or fnmatch(actual_value, rule_value)

    def _match_session_rules(self, operation: OperationRequest, effect: str) -> bool:
        """匹配会话级策略规则。"""
        if not self._conversation_store or not self._session_id:
            return False
        rules = self._conversation_store.list_session_rules(self._session_id)
        for rule in rules:
            if rule["effect"] != effect:
                continue
            if (
                self._matches_rule(rule["tool"], operation.tool)
                and self._matches_rule(rule["action"], operation.action)
                and fnmatch(operation.resource, rule["resource"])
            ):
                return True
        return False

    def _match_temp_grant(self, operation: OperationRequest) -> bool:
        for index, grant in enumerate(self._temp_grants):
            if self._matches_rule(grant.tool, operation.tool) and self._matches_rule(
                grant.action,
                operation.action,
            ) and fnmatch(operation.resource, grant.resource):
                if grant.scope == "once":
                    self._temp_grants.pop(index)
                return True
        return False

    def _handle_user_decision(self, operation: OperationRequest, answer: str) -> bool:
        if answer in {"1", "y"}:
            # 允许一次
            return True

        if answer == "2":
            # 本会话允许（精确路径）
            self._grant_session(operation, operation.resource)
            return True

        if answer == "3":
            # 允许当前文件夹 — 泛化到父目录下的 *
            folder_glob = _generalize_resource(operation.resource, levels=1)
            self._grant_session(operation, folder_glob)
            return True

        if answer == "4":
            # 允许父目录 — 泛化到祖父目录下的 *
            parent_glob = _generalize_resource(operation.resource, levels=2)
            self._grant_session(operation, parent_glob)
            return True

        if answer == "5":
            # 允许该工具所有操作 — 持久规则 tool=当前, action=*, resource=*
            self._persist_rule(operation, effect="allow", action="*", resource="*")
            return True

        if answer == "6":
            # 允许所有中低风险操作 — 持久规则 tool=*, action=*, resource=*, max_risk=medium
            self._persist_rule(
                operation, effect="allow", tool="*", action="*", resource="*", max_risk="medium",
            )
            return True

        if answer == "7":
            # 始终允许（精确路径）— 持久规则
            self._persist_rule(operation, effect="allow")
            return True

        if answer in {"8", "n"}:
            # 始终拒绝
            self._persist_rule(operation, effect="deny")
            return False

        print("[Policy Guard] 输入无效，默认拒绝")
        return False

    def _grant_session(self, operation: OperationRequest, resource: str) -> None:
        """写入会话级允许规则 + 内存临时授权。"""
        if self._conversation_store and self._session_id:
            self._conversation_store.create_session_rule(
                session_id=self._session_id,
                tool=operation.tool,
                action=operation.action,
                resource=resource,
                effect="allow",
            )
            print(f"[Policy Guard] 已写入会话允许规则: {resource}")
        self._temp_grants.append(
            TempGrant(
                tool=operation.tool,
                action=operation.action,
                resource=resource,
                scope="session",
            )
        )

    def _persist_rule(
        self,
        operation: OperationRequest,
        effect: str,
        *,
        tool: str | None = None,
        action: str | None = None,
        resource: str | None = None,
        max_risk: str | None = None,
    ) -> None:
        rule = PolicyRule(
            id=str(uuid4()),
            tool=tool or operation.tool,
            action=action or operation.action,
            resource=resource or str(Path(operation.resource)),
            effect=effect,
            created_at=datetime.now().isoformat(timespec="seconds"),
            expires_at=None,
            max_risk=max_risk,
        )
        self._rule_store.add_rule(rule)
        print(f"[Policy Guard] 已写入持久规则: {effect} → {rule.tool}/{rule.action}/{rule.resource}")
