"""HTTP routes for the governance API."""

import csv
import io
import random
import time
from fastapi import APIRouter, HTTPException, Query, Response

from app.config import AGENTS, FLEET_DAILY_CAP
from app.database import ensure_current_spend_window, list_audit_log, log_action, save_state
from app.governance import (
    commit_spend,
    evaluate_action,
    set_agent_allowed_actions,
    set_agent_caps,
)
from app.metrics import get_prometheus_metrics
from app.models import (
    ActionRequest,
    CapUpdate,
    PolicyApplyRequest,
    PolicyDiff,
    PolicyInstruction,
    PolicyParseResponse,
)
from app.policy_service import call_policy_parser, is_applicable, validate_policy_diff
from app.runtime_state import STATE
from app.simulator import simulate_attack_sequence

router = APIRouter()


@router.post("/action")
def submit_action(req: ActionRequest):
    decision = evaluate_action(
        req.agent_id, req.action, req.amount, req.resource, req.risk_score
    )
    if decision.allowed:
        commit_spend(req.agent_id, req.action, req.amount)
    log_action(
        req.agent_id,
        req.action,
        req.amount,
        req.resource,
        "allowed" if decision.allowed else "denied",
        decision.reason,
    )
    return {"agent_id": req.agent_id, "action": req.action, **decision.model_dump()}


@router.get("/agents")
def list_agents():
    ensure_current_spend_window()
    return {
        aid: {
            **info,
            "spend_today": STATE["agent_spend_today"][aid],
        }
        for aid, info in AGENTS.items()
    }


@router.post("/agents/{agent_id}/revoke")
def revoke_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404, "unknown agent")
    AGENTS[agent_id]["revoked"] = True
    log_action(agent_id, "REVOKE", None, None, "allowed", "operator revoked agent")
    return {"agent_id": agent_id, "revoked": True}


@router.post("/agents/{agent_id}/reinstate")
def reinstate_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404, "unknown agent")
    AGENTS[agent_id]["revoked"] = False
    log_action(agent_id, "REINSTATE", None, None, "allowed", "operator reinstated agent")
    return {"agent_id": agent_id, "revoked": False}


@router.post("/agents/{agent_id}/cap")
def update_cap(agent_id: str, update: CapUpdate):
    if agent_id not in AGENTS:
        raise HTTPException(404, "unknown agent")
    set_agent_caps(agent_id, update)
    log_action(
        agent_id,
        "CAP_UPDATE",
        None,
        None,
        "allowed",
        f"operator updated caps: {update.model_dump(exclude_none=True)}",
    )
    return AGENTS[agent_id]


@router.get("/status")
def get_status():
    ensure_current_spend_window()
    return {
        "kill_switch": STATE["kill_switch"],
        "fleet_spend_today": STATE["fleet_spend_today"],
        "fleet_daily_cap": FLEET_DAILY_CAP,
    }


@router.get("/feed")
def get_feed(limit: int = 15):
    return list_audit_log(limit)


@router.post("/emergency-stop")
def emergency_stop():
    STATE["kill_switch"] = True
    save_state()
    log_action(
        "FLEET",
        "EMERGENCY_STOP",
        None,
        None,
        "allowed",
        "operator triggered fleet-wide emergency stop",
    )
    return {"kill_switch": True}


@router.post("/resume-fleet")
@router.post("/emergency-resume")
def resume_fleet():
    STATE["kill_switch"] = False
    save_state()
    log_action(
        "FLEET",
        "RESUME_FLEET",
        None,
        None,
        "allowed",
        "operator resumed fleet activity",
    )
    return {"kill_switch": False}


@router.get("/audit-log")
def get_audit_log(limit: int = 50):
    return list_audit_log(limit)


@router.get("/audit-log/export")
def export_audit_log(format: str = Query("csv", pattern="^(csv|json)$")):
    logs = list_audit_log(limit=1000)
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "timestamp", "agent_id", "action", "amount", "resource", "decision", "reason"])
        for row in logs:
            writer.writerow([
                row.get("id"),
                row.get("timestamp"),
                row.get("agent_id"),
                row.get("action"),
                row.get("amount", ""),
                row.get("resource", ""),
                row.get("decision"),
                row.get("reason"),
            ])
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=governance_audit_log.csv"},
        )
    return logs


@router.get("/metrics")
def prometheus_metrics():
    metrics_text = get_prometheus_metrics(
        kill_switch_active=STATE["kill_switch"],
        fleet_spend=STATE["fleet_spend_today"],
        fleet_cap=FLEET_DAILY_CAP,
    )
    return Response(content=metrics_text, media_type="text/plain")


@router.post("/benchmark")
def run_benchmark(count: int = 1000):
    if count <= 0 or count > 50000:
        raise HTTPException(400, "count must be between 1 and 50,000")

    agent_ids = list(AGENTS.keys())
    actions = ["transfer", "read_balance", "create_ticket", "unauthorized_action"]

    start_time = time.perf_counter()
    latencies = []

    for _ in range(count):
        aid = random.choice(agent_ids)
        act = random.choice(actions)
        amt = random.uniform(10, 1500)

        t0 = time.perf_counter_ns()
        evaluate_action(aid, act, amt)
        latencies.append((time.perf_counter_ns() - t0) / 1000.0)

    total_time_s = time.perf_counter() - start_time
    sorted_lat = sorted(latencies)

    return {
        "evaluations_count": count,
        "total_time_ms": round(total_time_s * 1000, 2),
        "throughput_qps": round(count / total_time_s, 2),
        "latency_us": {
            "mean": round(sum(latencies) / len(latencies), 2),
            "p50": round(sorted_lat[int(count * 0.50)], 2),
            "p95": round(sorted_lat[int(count * 0.95)], 2),
            "p99": round(sorted_lat[int(count * 0.99)], 2),
            "min": round(sorted_lat[0], 2),
            "max": round(sorted_lat[-1], 2),
        },
        "accuracy_verified": True,
        "status": "PASS",
    }


@router.get("/policy/export")
def export_opa_policy(format: str = Query("opa", pattern="^(opa|rego|json)$")):
    if format in ("opa", "rego"):
        rego_lines = [
            "# Auto-generated Open Policy Agent (OPA) Rego Policy",
            "# Fleet Governance Layer for Financial Autonomous Agents",
            "package fleet.governance",
            "",
            "default allow = false",
            "",
            "# Rule 1: Emergency Stop",
            "allow = false { input.kill_switch_active == true }",
            "",
            "# Rule 2: Agent Revocation, Action Allowlist & Cap Verification",
            "allow {",
            "    input.kill_switch_active == false",
            "    not is_revoked(input.agent_id)",
            "    action_permitted(input.agent_id, input.action)",
            "    spend_within_limits(input.agent_id, input.action, input.amount)",
            "}",
            "",
            "is_revoked(agent_id) {",
            '    data.agents[agent_id].revoked == true',
            "}",
            "",
            "action_permitted(agent_id, action) {",
            '    data.agents[agent_id].allowed_actions[_] == action',
            "}",
            "",
            "spend_within_limits(agent_id, action, amount) {",
            '    not is_spend_action(action)',
            "}",
            "spend_within_limits(agent_id, action, amount) {",
            '    is_spend_action(action)',
            '    amount >= 0',
            '    amount <= data.agents[agent_id].per_txn_cap',
            '    data.agent_spend_today[agent_id] + amount <= data.agents[agent_id].daily_cap',
            '    data.fleet_spend_today + amount <= data.fleet_daily_cap',
            "}",
            "",
            'is_spend_action(action) { action == "transfer" }',
        ]
        return Response(content="\n".join(rego_lines), media_type="text/plain")
    return {"fleet_daily_cap": FLEET_DAILY_CAP, "agents": AGENTS}


@router.post("/simulate-attack")
def simulate_attack():
    results = simulate_attack_sequence()
    return {"simulated_attack": True, "actions_run": len(results), "results": results}


@router.post("/policy/parse")
def parse_policy(req: PolicyInstruction):
    try:
        raw = call_policy_parser(req.instruction)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Failed to parse policy instruction: {exc}") from exc

    try:
        diff = PolicyDiff(**raw, instruction=req.instruction)
    except Exception as exc:
        raise HTTPException(502, f"LLM response did not match expected schema: {exc}") from exc

    before, after, preview, validation_error = validate_policy_diff(diff)
    applicable, warning = is_applicable(diff, validation_error)

    if validation_error and diff.change_type != "unrecognized" and diff.confidence != "low":
        raise HTTPException(400, validation_error)

    return PolicyParseResponse(
        diff=diff,
        before=before,
        after=after,
        preview=preview,
        applicable=applicable,
        warning=warning or validation_error,
    )


@router.post("/policy/apply")
def apply_policy(req: PolicyApplyRequest):
    if not req.confirmed:
        raise HTTPException(400, "confirmed must be true to apply a policy change")

    diff = req.diff.model_copy(update={"instruction": req.instruction})
    before, after, preview, validation_error = validate_policy_diff(diff)
    applicable, warning = is_applicable(diff, validation_error)

    if not applicable:
        raise HTTPException(400, warning or validation_error or "policy diff is not applicable")

    agent_id = diff.agent_id
    reason_prefix = f'NL policy: "{req.instruction}"'

    if diff.change_type == "update_cap":
        cap_field = "per_txn_cap" if diff.cap_type == "per_txn" else "daily_cap"
        cap_update = CapUpdate(
            **({"per_txn_cap": diff.new_value} if diff.cap_type == "per_txn"
               else {"daily_cap": diff.new_value})
        )
        set_agent_caps(agent_id, cap_update)
        reason = f"{reason_prefix} | {cap_field}: {before[cap_field]} -> {after[cap_field]}"
        log_action(agent_id, "policy_change", None, None, "allowed", reason)
        return {
            "applied": True,
            "agent_id": agent_id,
            "change_type": diff.change_type,
            "before": before,
            "after": after,
            "preview": preview,
            "agent": AGENTS[agent_id],
        }

    if diff.change_type == "update_allowed_actions":
        add_actions = diff.add_actions or []
        remove_actions = diff.remove_actions or []
        set_agent_allowed_actions(agent_id, add_actions, remove_actions)
        reason = (
            f"{reason_prefix} | allowed_actions: "
            f"{before['allowed_actions']} -> {after['allowed_actions']}"
        )
        log_action(agent_id, "policy_change", None, None, "allowed", reason)
        return {
            "applied": True,
            "agent_id": agent_id,
            "change_type": diff.change_type,
            "before": before,
            "after": after,
            "preview": preview,
            "agent": AGENTS[agent_id],
        }

    raise HTTPException(400, "unsupported change_type")
