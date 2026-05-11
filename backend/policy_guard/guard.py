from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path
from uuid import uuid4

from backend.memory.rule_store import RuleStore
from backend.models import OperationRequest
from backend.policy_guard.rules import PolicyRule


@dataclass(slots=True)
class TempGrant:
    tool: str
    action: str
    resource: str
    scope: str


class PolicyGuard:
    """Policy guard with persistent rules and in-memory temp authorization."""

    def __init__(
        self,
        input_func=input,  # noqa: A002
        rule_store: RuleStore | None = None,
    ) -> None:
        self._input = input_func
        self._rule_store = rule_store or RuleStore()
        self._temp_grants: list[TempGrant] = []

    def approve(self, operation: OperationRequest) -> bool:
        persistent_rules = self._active_persistent_rules()

        if self._match_effect(persistent_rules, operation, "deny"):
            print("[Policy Guard] 命中持久 deny 规则，已拒绝")
            return False

        if self._match_effect(persistent_rules, operation, "allow"):
            print("[Policy Guard] 命中持久 allow 规则，自动放行")
            return True

        if self._match_temp_grant(operation):
            print("[Policy Guard] 命中临时授权，自动放行")
            return True

        print("\n[Policy Guard] 待审批操作：")
        print(operation.to_dict())

        answer = self._input(
            "请选择：1)允许一次(y) 2)本会话允许 3)始终允许 4)始终拒绝(n): "
        ).strip().lower()
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
            if self._matches_rule(rule.tool, operation.tool) and self._matches_rule(
                rule.action,
                operation.action,
            ) and fnmatch(operation.resource, rule.resource):
                return True
        return False

    def _matches_rule(self, rule_value: str, actual_value: str) -> bool:
        return rule_value == "*" or fnmatch(actual_value, rule_value)

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
            return True
        if answer == "2":
            self._temp_grants.append(
                TempGrant(
                    tool=operation.tool,
                    action=operation.action,
                    resource=operation.resource,
                    scope="session",
                )
            )
            return True
        if answer == "3":
            self._persist_rule(operation, effect="allow")
            return True
        if answer == "4":
            self._persist_rule(operation, effect="deny")
            return False
        if answer == "n":
            return False

        print("[Policy Guard] 输入无效，默认拒绝")
        return False

    def _persist_rule(self, operation: OperationRequest, effect: str) -> None:
        rule = PolicyRule(
            id=str(uuid4()),
            tool=operation.tool,
            action=operation.action,
            resource=str(Path(operation.resource)),
            effect=effect,
            created_at=datetime.now().isoformat(timespec="seconds"),
            expires_at=None,
        )
        self._rule_store.add_rule(rule)
        print(f"[Policy Guard] 已写入持久规则: {effect}")
