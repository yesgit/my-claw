from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend.memory.rule_store import RuleStore
from backend.policy_guard.rules import PolicyRule


class TestRuleStore(unittest.TestCase):
    def test_add_and_get_rule(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            rule = _sample_rule("r-1")
            store.add_rule(rule)

            loaded = store.get_rule("r-1")
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(loaded.id, "r-1")
            self.assertEqual(loaded.effect, "allow")

    def test_delete_rule(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            store.add_rule(_sample_rule("r-1"))

            deleted = store.delete_rule("r-1")
            self.assertTrue(deleted)
            self.assertIsNone(store.get_rule("r-1"))

    def test_delete_missing_rule_returns_false(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")

            self.assertFalse(store.delete_rule("missing"))

    def test_clear_expired_rules_only_deletes_expired(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            store = RuleStore(Path(tmp_dir) / "rules.db")
            store.add_rule(
                _sample_rule(
                    "expired",
                    expires_at=(datetime.now() - timedelta(hours=1)).isoformat(timespec="seconds"),
                )
            )
            store.add_rule(
                _sample_rule(
                    "active",
                    expires_at=(datetime.now() + timedelta(hours=1)).isoformat(timespec="seconds"),
                )
            )

            deleted = store.clear_expired_rules()

            self.assertEqual(deleted, 1)
            self.assertIsNone(store.get_rule("expired"))
            self.assertIsNotNone(store.get_rule("active"))


def _sample_rule(rule_id: str, expires_at: str | None = None) -> PolicyRule:
    return PolicyRule(
        id=rule_id,
        tool="filesystem",
        action="write_file",
        resource="/tmp/*",
        effect="allow",
        created_at=datetime.now().isoformat(timespec="seconds"),
        expires_at=expires_at,
    )


if __name__ == "__main__":
    unittest.main()
