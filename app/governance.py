"""Core governance decision engine."""

from typing import Optional

from app.config import AGENTS, FLEET_DAILY_CAP, SPEND_ACTIONS
from app.database import ensure_current_spend_window, save_state
from app.models import CapUpdate, GovernanceDecision
from app.runtime_state import STATE


def evaluate_action(agent_id: str, action: str, amount: float = 0.0,
                    resource: Optional[str] = None) -> GovernanceDecision:
    del resource
    ensure_current_spend_window()

    if STATE["kill_switch"]:
        return GovernanceDecision(allowed=False, reason="fleet-wide emergency stop is active")

    agent = AGENTS.get(agent_id)
    if agent is None:
        return GovernanceDecision(allowed=False, reason="unknown agent")

    if agent["revoked"]:
        return GovernanceDecision(allowed=False, reason=f"{agent_id} has been revoked")

    if action not in agent["allowed_actions"]:
        return GovernanceDecision(
            allowed=False,
            reason=f"'{action}' not in {agent_id}'s permitted actions {agent['allowed_actions']}",
        )

    if action in SPEND_ACTIONS:
        if amount < 0:
            return GovernanceDecision(allowed=False, reason="amount must be non-negative")
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
    if action in SPEND_ACTIONS:
        STATE["agent_spend_today"][agent_id] += amount
        STATE["fleet_spend_today"] += amount
        save_state()


def set_agent_caps(agent_id: str, update: CapUpdate) -> dict:
    if update.per_txn_cap is not None:
        AGENTS[agent_id]["per_txn_cap"] = update.per_txn_cap
    if update.daily_cap is not None:
        AGENTS[agent_id]["daily_cap"] = update.daily_cap
    return AGENTS[agent_id]


def set_agent_allowed_actions(agent_id: str, add_actions: list[str],
                              remove_actions: list[str]) -> dict:
    current = list(AGENTS[agent_id]["allowed_actions"])
    for action in remove_actions:
        if action in current:
            current.remove(action)
    for action in add_actions:
        if action not in current:
            current.append(action)
    AGENTS[agent_id]["allowed_actions"] = current
    return AGENTS[agent_id]
