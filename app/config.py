"""Static demo configuration for agents, actions, and model settings."""

from datetime import datetime, timezone

DB_PATH = "governance.db"

AGENTS: dict = {
    "payment_agent": {
        "display_name": "Payment Agent",
        "allowed_actions": ["transfer", "read_balance"],
        "per_txn_cap": 1000.0,
        "daily_cap": 5000.0,
        "revoked": False,
    },
    "support_agent": {
        "display_name": "Support Agent",
        "allowed_actions": ["read_balance", "create_ticket"],
        "per_txn_cap": 0.0,
        "daily_cap": 0.0,
        "revoked": False,
    },
    "fraud_agent": {
        "display_name": "Fraud Review Agent",
        "allowed_actions": ["read_balance", "flag_transaction", "freeze_account"],
        "per_txn_cap": 0.0,
        "daily_cap": 0.0,
        "revoked": False,
    },
}

FLEET_DAILY_CAP = 10000.0
SPEND_ACTIONS = {"transfer"}
PERMITTED_ACTIONS = {
    "transfer",
    "read_balance",
    "create_ticket",
    "flag_transaction",
    "freeze_account",
}

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-6"


def utc_today() -> str:
    return datetime.now(timezone.utc).date().isoformat()
