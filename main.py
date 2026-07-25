"""
Governance Layer for Financial Agents — Backend
Hackathon demo build. In-memory config + SQLite for persistence of audit log & state.

Flow for every incoming action:
  1. Global kill switch check
  2. Per-agent revocation check
  3. Policy check (is this action allowed for this agent?)
  4. Spend cap check (per-transaction, per-agent-daily, fleet-wide-daily)
  5. Execute (simulated) + always write to audit log
"""

import asyncio
import random
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

DB_PATH = "governance.db"

# ---------------------------------------------------------------------------
# Agent / policy configuration
# ---------------------------------------------------------------------------
# This mirrors what a real OPA/Rego policy would encode. Kept as a Python
# dict here for hackathon speed — the reasoning/structure is what matters.

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
        "per_txn_cap": 0.0,      # no spend actions
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

# Global state (kill switch + running spend totals). Kept in memory for speed,
# mirrored into SQLite so it survives a restart.
STATE = {
    "kill_switch": False,
    "agent_spend_today": {aid: 0.0 for aid in AGENTS},
    "fleet_spend_today": 0.0,
}

SPEND_ACTIONS = {"transfer"}  # actions that count against spend caps

# ---------------------------------------------------------------------------
# DB setup
# ---------------------------------------------------------------------------

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
                decision TEXT NOT NULL,     -- allowed | denied
                reason TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS global_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


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


# ---------------------------------------------------------------------------
# Governance core — this is the part your deck should zoom in on
# ---------------------------------------------------------------------------

class GovernanceDecision(BaseModel):
    allowed: bool
    reason: str


def evaluate_action(agent_id: str, action: str, amount: float = 0.0,
                     resource: Optional[str] = None) -> GovernanceDecision:
    # 1. Global kill switch — checked first, always, no exceptions
    if STATE["kill_switch"]:
        return GovernanceDecision(allowed=False, reason="fleet-wide emergency stop is active")

    agent = AGENTS.get(agent_id)
    if agent is None:
        return GovernanceDecision(allowed=False, reason="unknown agent")

    # 2. Per-agent revocation
    if agent["revoked"]:
        return GovernanceDecision(allowed=False, reason=f"{agent_id} has been revoked")

    # 3. Policy check — is this action in the agent's allowed list?
    if action not in agent["allowed_actions"]:
        return GovernanceDecision(
            allowed=False,
            reason=f"'{action}' not in {agent_id}'s permitted actions {agent['allowed_actions']}",
        )

    # 4. Spend cap checks (only relevant for spend-type actions)
    if action in SPEND_ACTIONS:
        if amount > agent["per_txn_cap"]:
            return GovernanceDecision(
                allowed=False,
                reason=f"amount {amount} exceeds per-transaction cap {agent['per_txn_cap']} for {agent_id}",
            )
        if STATE["agent_spend_today"][agent_id] + amount > agent["daily_cap"]:
            return GovernanceDecision(
                allowed=False,
                reason=f"would exceed {agent_id}'s daily cap {agent['daily_cap']}",
            )
        if STATE["fleet_spend_today"] + amount > FLEET_DAILY_CAP:
            return GovernanceDecision(
                allowed=False,
                reason=f"would exceed fleet-wide daily cap {FLEET_DAILY_CAP}",
            )

    return GovernanceDecision(allowed=True, reason="policy checks passed")


def commit_spend(agent_id: str, action: str, amount: float):
    """Only called after an action is allowed — updates running totals."""
    if action in SPEND_ACTIONS:
        STATE["agent_spend_today"][agent_id] += amount
        STATE["fleet_spend_today"] += amount


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

class ActionRequest(BaseModel):
    agent_id: str
    action: str
    amount: float = 0.0
    resource: Optional[str] = None


class CapUpdate(BaseModel):
    per_txn_cap: Optional[float] = None
    daily_cap: Optional[float] = None


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Agent Governance Layer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    asyncio.create_task(simulated_agent_traffic())


@app.post("/action")
def submit_action(req: ActionRequest):
    """The single entry point every agent action must pass through."""
    decision = evaluate_action(req.agent_id, req.action, req.amount, req.resource)
    if decision.allowed:
        commit_spend(req.agent_id, req.action, req.amount)
    log_action(req.agent_id, req.action, req.amount, req.resource,
               "allowed" if decision.allowed else "denied", decision.reason)
    return {"agent_id": req.agent_id, "action": req.action, **decision.model_dump()}


@app.get("/agents")
def list_agents():
    return {
        aid: {
            **info,
            "spend_today": STATE["agent_spend_today"][aid],
        }
        for aid, info in AGENTS.items()
    }


@app.post("/agents/{agent_id}/revoke")
def revoke_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404, "unknown agent")
    AGENTS[agent_id]["revoked"] = True
    log_action(agent_id, "REVOKE", None, None, "allowed", "operator revoked agent")
    return {"agent_id": agent_id, "revoked": True}


@app.post("/agents/{agent_id}/reinstate")
def reinstate_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404, "unknown agent")
    AGENTS[agent_id]["revoked"] = False
    log_action(agent_id, "REINSTATE", None, None, "allowed", "operator reinstated agent")
    return {"agent_id": agent_id, "revoked": False}


@app.post("/agents/{agent_id}/cap")
def update_cap(agent_id: str, update: CapUpdate):
    if agent_id not in AGENTS:
        raise HTTPException(404, "unknown agent")
    if update.per_txn_cap is not None:
        AGENTS[agent_id]["per_txn_cap"] = update.per_txn_cap
    if update.daily_cap is not None:
        AGENTS[agent_id]["daily_cap"] = update.daily_cap
    log_action(agent_id, "CAP_UPDATE", None, None, "allowed",
               f"operator updated caps: {update.model_dump(exclude_none=True)}")
    return AGENTS[agent_id]


@app.post("/emergency-stop")
def emergency_stop():
    STATE["kill_switch"] = True
    log_action("FLEET", "EMERGENCY_STOP", None, None, "allowed", "operator triggered fleet-wide emergency stop")
    return {"kill_switch": True}


@app.post("/emergency-resume")
def emergency_resume():
    STATE["kill_switch"] = False
    log_action("FLEET", "EMERGENCY_RESUME", None, None, "allowed", "operator resumed fleet operations")
    return {"kill_switch": False}


@app.get("/status")
def status():
    return {
        "kill_switch": STATE["kill_switch"],
        "fleet_spend_today": STATE["fleet_spend_today"],
        "fleet_daily_cap": FLEET_DAILY_CAP,
    }


@app.get("/audit-log")
def audit_log(limit: int = 100):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@app.get("/feed")
def feed(limit: int = 20):
    """Recent activity for the live dashboard feed — same data as audit log, smaller default."""
    return audit_log(limit=limit)


# ---------------------------------------------------------------------------
# Simulated agent traffic — so the dashboard has something live to show
# ---------------------------------------------------------------------------

SAMPLE_ACTIONS = [
    ("payment_agent", "transfer", lambda: round(random.uniform(50, 1500), 2)),
    ("payment_agent", "read_balance", lambda: 0.0),
    ("support_agent", "read_balance", lambda: 0.0),
    ("support_agent", "create_ticket", lambda: 0.0),
    ("fraud_agent", "read_balance", lambda: 0.0),
    ("fraud_agent", "flag_transaction", lambda: 0.0),
]


async def simulated_agent_traffic():
    """Background loop firing plausible agent actions every couple seconds."""
    await asyncio.sleep(2)  # let the server finish starting
    while True:
        agent_id, action, amount_fn = random.choice(SAMPLE_ACTIONS)
        amount = amount_fn()
        decision = evaluate_action(agent_id, action, amount, resource="acct_demo")
        if decision.allowed:
            commit_spend(agent_id, action, amount)
        log_action(agent_id, action, amount, "acct_demo",
                   "allowed" if decision.allowed else "denied", decision.reason)
        await asyncio.sleep(random.uniform(1.5, 3.5))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
