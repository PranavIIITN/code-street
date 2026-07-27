"""Background demo traffic generator."""

import asyncio
import random

from app.database import log_action
from app.governance import commit_spend, evaluate_action

def weighted_transfer_amount() -> float:
    bucket = random.choices(
        population=[
            (50, 300),
            (300, 800),
            (800, 1200),
            (1200, 2000),
        ],
        weights=[70, 22, 6, 2],
        k=1,
    )[0]
    return round(random.uniform(*bucket), 2)


SAMPLE_ACTIONS = [
    ("payment_agent", "transfer", weighted_transfer_amount),
    ("payment_agent", "read_balance", lambda: 0.0),
    ("support_agent", "read_balance", lambda: 0.0),
    ("support_agent", "create_ticket", lambda: 0.0),
    ("fraud_agent", "read_balance", lambda: 0.0),
    ("fraud_agent", "flag_transaction", lambda: 0.0),
]

ATTACK_ACTIONS = [
    ("payment_agent", "transfer", 50000.0),
    ("payment_agent", "transfer", 25000.0),
    ("payment_agent", "wire_transfer", 0.0),
    ("support_agent", "transfer", 500.0),
    ("fraud_agent", "transfer", 10000.0),
]


async def simulated_agent_traffic():
    await asyncio.sleep(2)
    while True:
        agent_id, action, amount_fn = random.choice(SAMPLE_ACTIONS)
        amount = amount_fn()
        decision = evaluate_action(agent_id, action, amount, resource="acct_demo")
        if decision.allowed:
            commit_spend(agent_id, action, amount)
        log_action(
            agent_id,
            action,
            amount,
            "acct_demo",
            "allowed" if decision.allowed else "denied",
            decision.reason,
        )
        await asyncio.sleep(random.uniform(1.5, 3.5))


async def simulate_attack_sequence() -> list[dict]:
    results = []
    for agent_id, action, amount in ATTACK_ACTIONS:
        decision = evaluate_action(agent_id, action, amount, resource="attack_simulation")
        if decision.allowed:
            commit_spend(agent_id, action, amount)
        log_action(
            agent_id,
            action,
            amount,
            "attack_simulation",
            "allowed" if decision.allowed else "denied",
            decision.reason,
        )
        results.append({
            "agent_id": agent_id,
            "action": action,
            "amount": amount,
            "allowed": decision.allowed,
            "reason": decision.reason,
        })
        await asyncio.sleep(0.2)
    return results
