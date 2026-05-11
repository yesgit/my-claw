from __future__ import annotations

import unittest

from backend.planner.simple_planner import SimplePlanner


class TestSimplePlanner(unittest.TestCase):
    def test_plan_with_json(self) -> None:
        planner = SimplePlanner()
        op = planner.plan(
            '{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":{"content":"x"},"risk":"medium"}'
        )

        self.assertEqual(op.tool, "filesystem")
        self.assertEqual(op.action, "write_file")
        self.assertEqual(op.resource, "/tmp/a.txt")

    def test_plan_with_free_text(self) -> None:
        planner = SimplePlanner()
        op = planner.plan("写个周报草稿")

        self.assertEqual(op.tool, "filesystem")
        self.assertEqual(op.action, "write_file")
        self.assertIn("output", op.resource)


if __name__ == "__main__":
    unittest.main()
