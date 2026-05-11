from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from backend.policy_guard.rules import PolicyRule


class RuleStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        default_path = Path.cwd() / "data" / "policy_rules.db"
        self._db_path = Path(db_path) if db_path else default_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS policy_rules (
                    id TEXT PRIMARY KEY,
                    tool TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    effect TEXT NOT NULL CHECK(effect IN ('allow', 'deny')),
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                )
                """
            )
            conn.commit()

    def add_rule(self, rule: PolicyRule) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO policy_rules (id, tool, action, resource, effect, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.id,
                    rule.tool,
                    rule.action,
                    rule.resource,
                    rule.effect,
                    rule.created_at,
                    rule.expires_at,
                ),
            )
            conn.commit()

    def list_rules(self) -> list[PolicyRule]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, tool, action, resource, effect, created_at, expires_at
                FROM policy_rules
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [
            PolicyRule(
                id=row[0],
                tool=row[1],
                action=row[2],
                resource=row[3],
                effect=row[4],
                created_at=row[5],
                expires_at=row[6],
            )
            for row in rows
        ]

    def get_rule(self, rule_id: str) -> PolicyRule | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, tool, action, resource, effect, created_at, expires_at
                FROM policy_rules
                WHERE id = ?
                """,
                (rule_id,),
            ).fetchone()

        if row is None:
            return None

        return PolicyRule(
            id=row[0],
            tool=row[1],
            action=row[2],
            resource=row[3],
            effect=row[4],
            created_at=row[5],
            expires_at=row[6],
        )

    def delete_rule(self, rule_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM policy_rules
                WHERE id = ?
                """,
                (rule_id,),
            )
            conn.commit()

        return cursor.rowcount > 0

    def clear_expired_rules(self, now: datetime | None = None) -> int:
        effective_now = (now or datetime.now()).isoformat(timespec="seconds")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM policy_rules
                WHERE expires_at IS NOT NULL
                AND expires_at <= ?
                """,
                (effective_now,),
            )
            conn.commit()

        return cursor.rowcount
