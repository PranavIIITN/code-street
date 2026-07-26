"""HTTP routes for the governance API."""

from fastapi import APIRouter, HTTPException, Query

from app.config import AGENTS, FLEET_DAILY_CAP
from app.database import ensure_current_spend_window, list_audit_log, log_action, save_state
from app.governance import (
    commit_spend,
    evaluate_action,
    set_agent_allowed_actions,
    set_agent_caps,
)
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
    decision = evaluate_action(req.agent_id, req.action, req.amount, req.resource)
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


@router.post("/emergency-resume")
def emergency_resume():
    STATE["kill_switch"] = False
    save_state()
    log_action(
        "FLEET",
        "EMERGENCY_RESUME",
        None,
        None,
        "allowed",
        "operator resumed fleet operations",
    )
    return {"kill_switch": False}


@router.get("/status")
def status():
    ensure_current_spend_window()
    return {
        "kill_switch": STATE["kill_switch"],
        "fleet_spend_today": STATE["fleet_spend_today"],
        "fleet_daily_cap": FLEET_DAILY_CAP,
        "spend_date": STATE["spend_date"],
    }


@router.get("/audit-log")
def audit_log(limit: int = Query(100, ge=1, le=500)):
    return list_audit_log(limit)


@router.get("/feed")
def feed(limit: int = Query(20, ge=1, le=100)):
    return list_audit_log(limit)


@router.post("/simulate-attack")
async def simulate_attack():
    return {"results": await simulate_attack_sequence()}


@router.post("/policy/parse", response_model=PolicyParseResponse)
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
