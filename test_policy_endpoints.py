#!/usr/bin/env python3
"""
Exercise POST /policy/parse and POST /policy/apply with example instructions.

Requires the server running on http://127.0.0.1:8000 and ANTHROPIC_API_KEY set
for parse tests. Validation/apply paths are also tested with handcrafted diffs.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional


BASE = os.environ.get("GOVERNANCE_API", "http://127.0.0.1:8000")


def api(method: str, path: str, body: Optional[dict] = None) -> tuple:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, raw


def print_section(title: str):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def test_parse(instruction: str):
    print_section(f'PARSE: "{instruction}"')
    status, result = api("POST", "/policy/parse", {"instruction": instruction})
    print(f"HTTP {status}")
    print(json.dumps(result, indent=2))
    return status, result


def test_apply(instruction: str, diff: dict):
    print_section(f'APPLY: "{instruction}"')
    payload = {"confirmed": True, "instruction": instruction, "diff": diff}
    status, result = api("POST", "/policy/apply", payload)
    print(f"HTTP {status}")
    print(json.dumps(result, indent=2))
    return status, result


def test_validation_rejects_bad_agent():
    print_section("VALIDATION: reject hallucinated agent_id (no LLM)")
    diff = {
        "agent_id": "ghost_agent",
        "change_type": "update_cap",
        "cap_type": "daily",
        "new_value": 1000,
        "add_actions": None,
        "remove_actions": None,
        "confidence": "high",
        "explanation": "test",
    }
    status, result = api("POST", "/policy/apply", {
        "confirmed": True,
        "instruction": "test bad agent",
        "diff": diff,
    })
    print(f"HTTP {status} (expected 400)")
    print(json.dumps(result, indent=2))


def main():
    print(f"Target: {BASE}")
    print(f"ANTHROPIC_API_KEY set: {'yes' if os.environ.get('ANTHROPIC_API_KEY') else 'NO'}")

    # Always test server-side validation without LLM
    test_validation_rejects_bad_agent()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nSkipping LLM parse tests — set ANTHROPIC_API_KEY to run full examples.")
        sys.exit(0)

    examples = [
        "cut payment_agent's daily cap to $3,000",
        "let fraud_agent create tickets too",
        "revoke payment_agent immediately",  # out of scope → unrecognized/low confidence
    ]

    parsed = []
    for instruction in examples:
        status, result = test_parse(instruction)
        if status == 200 and isinstance(result, dict) and result.get("applicable"):
            parsed.append((instruction, result))

    if parsed:
        instruction, result = parsed[0]
        diff = result["diff"]
        # Drop server-added instruction field from diff if present for clean echo-back
        diff.pop("instruction", None)
        test_apply(instruction, diff)

        print_section("AUDIT LOG (policy_change entries)")
        status, rows = api("GET", "/audit-log?limit=5")
        if status == 200:
            policy_rows = [r for r in rows if r.get("action") == "policy_change"]
            print(json.dumps(policy_rows[:3], indent=2))
    else:
        print("\nNo applicable diffs to apply from parse examples.")


if __name__ == "__main__":
    main()
