"""Unit tests for natural-language policy validation and application."""

import copy
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.config import AGENTS
from app.models import PolicyApplyRequest, PolicyDiff
from app.policy_service import is_applicable, validate_policy_diff
from app.routes import apply_policy


class PolicyServiceTests(unittest.TestCase):
    def setUp(self):
        self._agents = copy.deepcopy(AGENTS)

    def tearDown(self):
        AGENTS.clear()
        AGENTS.update(self._agents)

    def diff(self, **overrides):
        data = {
            "agent_id": "payment_agent",
            "change_type": "update_cap",
            "cap_type": "daily",
            "new_value": 3000,
            "add_actions": None,
            "remove_actions": None,
            "confidence": "high",
            "explanation": "Lower the daily cap.",
        }
        data.update(overrides)
        return PolicyDiff(**data)

    def test_validate_cap_diff_returns_preview_and_before_after(self):
        before, after, preview, error = validate_policy_diff(self.diff())

        self.assertIsNone(error)
        self.assertEqual(before, {"daily_cap": 5000.0})
        self.assertEqual(after, {"daily_cap": 3000.0})
        self.assertEqual(preview, "payment_agent daily cap: $5,000 -> $3,000")

    def test_validate_rejects_unknown_agent(self):
        _, _, _, error = validate_policy_diff(self.diff(agent_id="ghost_agent"))

        self.assertEqual(error, "unknown agent 'ghost_agent'")

    def test_validate_rejects_unknown_action(self):
        diff = self.diff(
            change_type="update_allowed_actions",
            cap_type=None,
            new_value=None,
            add_actions=["wire_transfer"],
        )

        _, _, _, error = validate_policy_diff(diff)

        self.assertIn("unknown action(s)", error)
        self.assertIn("wire_transfer", error)

    def test_low_confidence_diff_is_not_applicable(self):
        applicable, warning = is_applicable(self.diff(confidence="low"), None)

        self.assertFalse(applicable)
        self.assertIn("Confidence is too low", warning)

    @patch("app.routes.log_action")
    def test_apply_policy_updates_daily_cap(self, log_action):
        req = PolicyApplyRequest(
            confirmed=True,
            instruction="cut payment_agent's daily cap to $3,000",
            diff=self.diff(),
        )

        result = apply_policy(req)

        self.assertTrue(result["applied"])
        self.assertEqual(AGENTS["payment_agent"]["daily_cap"], 3000)
        log_action.assert_called_once()
        self.assertIn("daily_cap: 5000.0 -> 3000.0", log_action.call_args.args[5])

    def test_apply_policy_requires_confirmation(self):
        req = PolicyApplyRequest(
            confirmed=False,
            instruction="cut payment_agent's daily cap to $3,000",
            diff=self.diff(),
        )

        with self.assertRaises(HTTPException) as ctx:
            apply_policy(req)

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "confirmed must be true to apply a policy change")


if __name__ == "__main__":
    unittest.main()
