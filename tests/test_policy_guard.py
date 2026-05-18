from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.memory.rule_store import RuleStore
from backend.models import OperationRequest
from backend.policy_guard.guard import PolicyGuard, TempGrant
from backend.policy_guard.rules import PolicyRule


class TestPolicyGuard(unittest.TestCase):
    def test_approve_returns_true_when_input_is_y(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "y", rule_store=store)
            op = _sample_op("/tmp/a.txt")

            self.assertTrue(guard.approve(op))

    def test_approve_returns_false_when_input_is_n(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "n", rule_store=store)
            op = _sample_op("/tmp/a.txt")

            self.assertFalse(guard.approve(op))

    def test_deny_rule_has_higher_priority_than_allow(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            allow_rule = PolicyRule(
                id="allow-1",
                tool="filesystem",
                action="write_file",
                resource="/tmp/*",
                effect="allow",
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            deny_rule = PolicyRule(
                id="deny-1",
                tool="filesystem",
                action="write_file",
                resource="/tmp/a.txt",
                effect="deny",
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            store.add_rule(allow_rule)
            store.add_rule(deny_rule)

            guard = PolicyGuard(input_func=lambda _: "y", rule_store=store)
            self.assertFalse(guard.approve(_sample_op("/tmp/a.txt")))

    def test_allow_rule_auto_approves_with_wildcard(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            store.add_rule(
                PolicyRule(
                    id="allow-wildcard",
                    tool="filesystem",
                    action="write_file",
                    resource="/tmp/report/*",
                    effect="allow",
                    created_at=datetime.now().isoformat(timespec="seconds"),
                )
            )

            guard = PolicyGuard(input_func=lambda _: "n", rule_store=store)
            self.assertTrue(guard.approve(_sample_op("/tmp/report/week-20.md")))

    def test_expired_rule_is_ignored(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            store.add_rule(
                PolicyRule(
                    id="expired-allow",
                    tool="filesystem",
                    action="write_file",
                    resource="/tmp/*",
                    effect="allow",
                    created_at=datetime.now().isoformat(timespec="seconds"),
                    expires_at=(datetime.now() - timedelta(days=1)).isoformat(timespec="seconds"),
                )
            )

            guard = PolicyGuard(input_func=lambda _: "n", rule_store=store)
            self.assertFalse(guard.approve(_sample_op("/tmp/a.txt")))

    def test_session_grant_allows_same_operation_without_prompt(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            answers = iter(["2"])  # first call chooses session allow
            guard = PolicyGuard(input_func=lambda _: next(answers, "n"), rule_store=store)
            op = _sample_op("/tmp/a.txt")

            self.assertTrue(guard.approve(op))
            self.assertTrue(guard.approve(op))

    def test_once_grant_is_consumed_after_first_match(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "n", rule_store=store)
            guard._temp_grants = [  # noqa: SLF001
                TempGrant(
                    tool="filesystem",
                    action="write_file",
                    resource="/tmp/a.txt",
                    scope="once",
                )
            ]

            self.assertTrue(guard.approve(_sample_op("/tmp/a.txt")))
            self.assertFalse(guard.approve(_sample_op("/tmp/a.txt")))

    def test_choose_always_allow_persists_rule(self) -> None:
        """选项 7 = 始终允许（精确路径），应写入持久规则。"""
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "7", rule_store=store)
            op = _sample_op("/tmp/a.txt")

            self.assertTrue(guard.approve(op))
            self.assertTrue(any(r.effect == "allow" for r in store.list_rules()))

    def test_choose_always_deny_persists_rule(self) -> None:
        """选项 8 = 始终拒绝，应写入持久规则。"""
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "8", rule_store=store)
            op = _sample_op("/tmp/a.txt")

            self.assertFalse(guard.approve(op))
            self.assertTrue(any(r.effect == "deny" for r in store.list_rules()))

    def test_folder_glob_session_allow(self) -> None:
        """选项 3 = 允许当前文件夹，应写入 session 规则 + temp grant。"""
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            answers = iter(["3"])
            guard = PolicyGuard(input_func=lambda _: next(answers, "n"), rule_store=store)
            op = _sample_op("/tmp/sub/a.txt")

            self.assertTrue(guard.approve(op))
            # 同文件夹下其他文件也应放行（命中 temp grant）
            self.assertTrue(guard.approve(_sample_op("/tmp/sub/b.txt")))

    def test_tool_all_persistent_rule(self) -> None:
        """选项 5 = 允许该工具所有操作，应写入持久规则 tool=当前, action=*, resource=*。"""
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "5", rule_store=store)
            op = _sample_op("/tmp/a.txt")

            self.assertTrue(guard.approve(op))
            rules = store.list_rules()
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0].tool, "filesystem")
            self.assertEqual(rules[0].action, "*")
            self.assertEqual(rules[0].resource, "*")
            self.assertEqual(rules[0].effect, "allow")

    def test_medium_risk_persistent_rule(self) -> None:
        """选项 6 = 允许所有中低风险，应写入持久规则 max_risk=medium。"""
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            guard = PolicyGuard(input_func=lambda _: "6", rule_store=store)

            self.assertTrue(guard.approve(_sample_op("/tmp/a.txt")))
            rules = store.list_rules()
            self.assertEqual(len(rules), 1)
            self.assertEqual(rules[0].tool, "*")
            self.assertEqual(rules[0].max_risk, "medium")
            # medium 风险应匹配
            self.assertTrue(guard.approve(_sample_op("/tmp/b.txt")))

    def test_max_risk_high_rejected(self) -> None:
        """max_risk=medium 的规则不应放行 high 风险操作。"""
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            store.add_rule(
                PolicyRule(
                    id="risk-cap",
                    tool="*",
                    action="*",
                    resource="*",
                    effect="allow",
                    created_at=datetime.now().isoformat(timespec="seconds"),
                    max_risk="medium",
                )
            )
            guard = PolicyGuard(input_func=lambda _: "n", rule_store=store)
            # medium 应放行
            self.assertTrue(guard.approve(OperationRequest(
                tool="filesystem", action="write_file", resource="/tmp/a.txt",
                params={}, risk="medium",
            )))
            # high 应拒绝
            self.assertFalse(guard.approve(OperationRequest(
                tool="filesystem", action="delete", resource="/tmp/a.txt",
                params={}, risk="high",
            )))


def _sample_op(resource: str) -> OperationRequest:
    return OperationRequest(
        tool="filesystem",
        action="write_file",
        resource=resource,
        params={"mode": "overwrite", "content": "hello"},
        risk="medium",
    )


if __name__ == "__main__":
    unittest.main()
