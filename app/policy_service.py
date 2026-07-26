"""Natural-language policy parsing and validation service."""

import json
import os
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import HTTPException

from app.config import AGENTS, ANTHROPIC_API_URL, ANTHROPIC_MODEL, PERMITTED_ACTIONS
from app.models import PolicyDiff

POLICY_SYSTEM_PROMPT = f"""You parse plain-English fleet policy change instructions into structured JSON.

Known agents: {", ".join(AGENTS.keys())}
Known actions: {", ".join(sorted(PERMITTED_ACTIONS))}
Cap types: per_txn (per-transaction spend limit), daily (daily spend limit)

Return ONLY valid JSON - no markdown, no prose - matching this exact schema:
{{
  "agent_id": "<agent_id>" | null,
  "change_type": "update_cap" | "update_allowed_actions" | "unrecognized",
  "cap_type": "per_txn" | "daily" | null,
  "new_value": <positive number> | null,
  "add_actions": [<action names>] | null,
  "remove_actions": [<action names>] | null,
  "confidence": "high" | "medium" | "low",
  "explanation": "<one sentence explaining what will change>"
}}

Rules:
- Use update_cap when changing spend limits. Set cap_type and new_value accordingly.
- Use update_allowed_actions when granting or revoking permitted actions. Use add_actions and/or remove_actions.
- Use unrecognized with low confidence if the instruction is ambiguous, out of scope (revocation, kill switch, fleet caps), or cannot be mapped safely.
- Never invent agent IDs or action names outside the known lists.
- For cap changes, new_value must be a positive number."""


def call_policy_parser(instruction: str) -> dict:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        payload = json.dumps({
            "model": ANTHROPIC_MODEL,
            "max_tokens": 500,
            "system": POLICY_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": instruction}],
        }).encode("utf-8")

        request = Request(
            ANTHROPIC_API_URL,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
            content_blocks = body.get("content") or []
            text_parts = [
                block.get("text", "")
                for block in content_blocks
                if block.get("type") == "text"
            ]
            if text_parts:
                return extract_json("".join(text_parts))
        except Exception:
            pass

    return fallback_policy_parser(instruction)


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


def validate_policy_diff(
    diff: PolicyDiff,
) -> tuple[Optional[dict], Optional[dict], Optional[str], Optional[str]]:
    if diff.change_type == "unrecognized":
        return None, None, None, "Instruction could not be mapped to a supported policy change"

    if not diff.agent_id:
        return None, None, None, "agent_id is required for applicable policy changes"

    if diff.agent_id not in AGENTS:
        return None, None, None, f"unknown agent '{diff.agent_id}'"

    agent = AGENTS[diff.agent_id]

    if diff.change_type == "update_cap":
        if diff.cap_type not in ("per_txn", "daily"):
            return None, None, None, "cap_type must be 'per_txn' or 'daily' for cap updates"
        if diff.new_value is None or diff.new_value <= 0:
            return None, None, None, "new_value must be a positive number for cap updates"

        cap_field = "per_txn_cap" if diff.cap_type == "per_txn" else "daily_cap"
        before_val = agent[cap_field]
        after_val = float(diff.new_value)
        before = {cap_field: before_val}
        after = {cap_field: after_val}
        preview = format_cap_preview(diff.agent_id, diff.cap_type, before_val, after_val)
        return before, after, preview, None

    if diff.change_type == "update_allowed_actions":
        add_actions = diff.add_actions or []
        remove_actions = diff.remove_actions or []
        if not add_actions and not remove_actions:
            return None, None, None, "add_actions or remove_actions required for action updates"

        unknown = [a for a in add_actions + remove_actions if a not in PERMITTED_ACTIONS]
        if unknown:
            return None, None, None, f"unknown action(s): {unknown}. Valid actions: {sorted(PERMITTED_ACTIONS)}"

        current = list(agent["allowed_actions"])
        missing = [a for a in remove_actions if a not in current]
        if missing:
            return None, None, None, f"cannot remove actions not currently allowed: {missing}"

        after_actions = list(current)
        for action in remove_actions:
            after_actions.remove(action)
        for action in add_actions:
            if action not in after_actions:
                after_actions.append(action)

        if after_actions == current:
            return None, None, None, "policy change would leave allowed actions unchanged"

        before = {"allowed_actions": current}
        after = {"allowed_actions": after_actions}
        preview = format_actions_preview(
            diff.agent_id, current, after_actions, add_actions, remove_actions,
        )
        return before, after, preview, None

    return None, None, None, f"unsupported change_type '{diff.change_type}'"


def is_applicable(diff: PolicyDiff, validation_error: Optional[str]) -> tuple[bool, Optional[str]]:
    if validation_error:
        return False, validation_error
    if diff.change_type == "unrecognized":
        return False, "Instruction could not be mapped to a supported policy change"
    if diff.confidence == "low":
        return False, "Confidence is too low to apply this change automatically - please rephrase"
    return True, None


def format_cap_preview(agent_id: str, cap_type: str, before: float, after: float) -> str:
    label = "per-transaction" if cap_type == "per_txn" else "daily"
    return f"{agent_id} {label} cap: ${before:,.0f} -> ${after:,.0f}"


def format_actions_preview(agent_id: str, before: list[str], after: list[str],
                           add_actions: list[str], remove_actions: list[str]) -> str:
    parts = [f"{agent_id} allowed actions"]
    if remove_actions:
        parts.append(f"remove {', '.join(remove_actions)}")
    if add_actions:
        parts.append(f"add {', '.join(add_actions)}")
    parts.append(f"[{', '.join(before)}] -> [{', '.join(after)}]")
    return ": ".join(parts[:1]) + " - " + ", ".join(parts[1:])


import re

def fallback_policy_parser(instruction: str) -> dict:
    text = instruction.lower().strip()

    agent_id = None
    for aid in AGENTS.keys():
        if aid in text or aid.replace("_agent", "") in text:
            agent_id = aid
            break

    numbers = re.findall(r'\$?([0-9]{1,3}(?:,[0-9]{3})*|\d+)', text)
    if numbers and agent_id:
        val_str = numbers[-1].replace(',', '')
        try:
            val = float(val_str)
            cap_type = "per_txn" if ("per_txn" in text or "per transaction" in text or "per-transaction" in text or "txn" in text) else "daily"
            return {
                "agent_id": agent_id,
                "change_type": "update_cap",
                "cap_type": cap_type,
                "new_value": val,
                "add_actions": None,
                "remove_actions": None,
                "confidence": "high",
                "explanation": f"Set {agent_id}'s {cap_type} cap to ${val:,.0f}."
            }
        except ValueError:
            pass

    if agent_id:
        found_actions = [a for a in PERMITTED_ACTIONS if a in text]
        if found_actions:
            if any(k in text for k in ["add", "allow", "grant", "enable"]):
                return {
                    "agent_id": agent_id,
                    "change_type": "update_allowed_actions",
                    "cap_type": None,
                    "new_value": None,
                    "add_actions": found_actions,
                    "remove_actions": None,
                    "confidence": "high",
                    "explanation": f"Add {', '.join(found_actions)} to {agent_id} allowed actions."
                }
            elif any(k in text for k in ["remove", "revoke", "deny", "disable"]):
                return {
                    "agent_id": agent_id,
                    "change_type": "update_allowed_actions",
                    "cap_type": None,
                    "new_value": None,
                    "add_actions": None,
                    "remove_actions": found_actions,
                    "confidence": "high",
                    "explanation": f"Remove {', '.join(found_actions)} from {agent_id} allowed actions."
                }

    return {
        "agent_id": agent_id,
        "change_type": "unrecognized",
        "cap_type": None,
        "new_value": None,
        "add_actions": None,
        "remove_actions": None,
        "confidence": "low",
        "explanation": "Could not recognize policy instruction."
    }
