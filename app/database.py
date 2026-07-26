"""SQLite persistence for audit logs and restart-safe runtime state."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from app.config import AGENTS, DB_PATH, utc_today
from app.runtime_state import STATE


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                amount REAL,
                resource TEXT,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
    load_state()


def save_state():
    payload = {
        "kill_switch": STATE["kill_switch"],
        "agent_spend_today": STATE["agent_spend_today"],
        "fleet_spend_today": STATE["fleet_spend_today"],
        "spend_date": STATE["spend_date"],
    }
    with get_db() as conn:
        for key, value in payload.items():
            conn.execute(
                "INSERT OR REPLACE INTO global_state (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )


def ensure_current_spend_window():
    today = utc_today()
    if STATE["spend_date"] != today:
        STATE["spend_date"] = today
        STATE["agent_spend_today"] = {aid: 0.0 for aid in AGENTS}
        STATE["fleet_spend_today"] = 0.0
        save_state()


def load_state():
    with get_db() as conn:
        rows = conn.execute("SELECT key, value FROM global_state").fetchall()

    stored = {}
    for row in rows:
        try:
            stored[row["key"]] = json.loads(row["value"])
        except json.JSONDecodeError:
            continue

    today = utc_today()
    STATE["kill_switch"] = bool(stored.get("kill_switch", False))
    STATE["spend_date"] = today

    if stored.get("spend_date") == today:
        stored_agent_spend = stored.get("agent_spend_today", {})
        STATE["agent_spend_today"] = {
            aid: float(stored_agent_spend.get(aid, 0.0))
            for aid in AGENTS
        }
        STATE["fleet_spend_today"] = float(stored.get("fleet_spend_today", 0.0))
    else:
        STATE["agent_spend_today"] = {aid: 0.0 for aid in AGENTS}
        STATE["fleet_spend_today"] = 0.0

    save_state()


def log_action(agent_id: str, action: str, amount: Optional[float],
               resource: Optional[str], decision: str, reason: str):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_log (id, timestamp, agent_id, action, amount, resource, decision, reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                datetime.now(timezone.utc).isoformat(),
                agent_id,
                action,
                amount,
                resource,
                decision,
                reason,
            ),
        )


def list_audit_log(limit: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]
