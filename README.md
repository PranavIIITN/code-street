# Fleet Governance Layer

Fleet Governance Layer is a FastAPI demo for supervising autonomous financial
agents. Every agent action passes through a centralized governance service before
it is allowed to execute. The service enforces emergency controls, per-agent
permissions, spend limits, and audit logging, then exposes the result to a live
browser dashboard.

The project is intentionally small enough for a hackathon demo, but the backend
is organized like a production service: route handlers, governance logic,
persistence, runtime state, policy parsing, and background simulation live in
separate modules.

## What It Does

- Evaluates every agent action through a single controlled API.
- Blocks all actions when the fleet-wide emergency stop is active.
- Supports per-agent revoke and reinstate controls.
- Enforces action allowlists per agent.
- Enforces per-transaction, per-agent daily, and fleet-wide daily spend caps.
- Rejects negative spend attempts so totals cannot be manipulated downward.
- Persists audit logs to SQLite.
- Persists kill switch and daily spend state across backend restarts.
- Resets spend totals automatically when the UTC date changes.
- Simulates live agent traffic so the dashboard has activity immediately.
- Provides optional natural-language policy parsing through Anthropic.
- Serves a standalone `dashboard.html` that polls the API.
- Includes a simulated attack endpoint that injects deliberately risky actions
  into the normal audit/governance path.
- Provides React dashboard controls for attack simulation and natural-language
  policy changes.
- Shows gate-level decision transparency in the live feed and audit log.

## Build Plan and Status

The backend has already been refactored out of one large `main.py` file into
separate modules. The current implementation follows this rule:

- `app/routes.py` owns HTTP routing only.
- `app/governance.py` owns the core decision engine.
- `app/policy_service.py` owns natural-language policy parsing and validation.
- `app/database.py` owns SQLite persistence.
- `app/simulator.py` owns demo traffic and attack simulation.
- `main.py` only creates the FastAPI app and starts background tasks.

### Completed

1. Modular backend structure
   - Moved config, models, routes, database access, governance logic, policy
     parsing, runtime state, and simulator logic into dedicated modules.
   - Kept route handlers thin so business logic is easier to test and replace.

2. Core governance flow
   - Global emergency stop check.
   - Unknown-agent rejection.
   - Per-agent revocation check.
   - Per-agent action allowlist check.
   - Negative spend rejection.
   - Per-transaction cap enforcement.
   - Per-agent daily cap enforcement.
   - Fleet-wide daily cap enforcement.
   - Audit logging for both allowed and denied decisions.

3. Persistence and daily reset
   - Audit rows are stored in `governance.db`.
   - Kill switch state and current spend totals persist across restarts.
   - Daily spend windows reset automatically by UTC date.

4. Natural-language policy editor
   - `POST /policy/parse` converts plain-English instructions into structured
     policy diffs using Anthropic.
   - `POST /policy/apply` applies confirmed diffs only after server-side
     validation.
   - Validation rejects unknown agents, unknown actions, unsafe changes,
     unsupported changes, low-confidence changes, and no-op changes.

5. Simulated attack endpoint
   - `POST /simulate-attack` runs five deliberately risky actions through the
     existing governance engine.
   - Each attack action is written to the audit log through the normal path.
   - A short delay between actions makes the cascade visible in the dashboard.

6. Realistic traffic distribution
   - Payment transfer amounts are generated with weighted buckets instead of a
     flat uniform range.
   - Routine transfers: 70% weight, `$50-$300`.
   - Medium transfers: 22% weight, `$300-$800`.
   - Large transfers: 6% weight, `$800-$1,200`.
   - Anomalous transfers: 2% weight, `$1,200-$2,000`.
   - The anomalous bucket intentionally creates occasional organic denials
     against the `$1,000` per-transaction cap.

7. Dashboard controls
   - Added a React dashboard Simulate Attack button near the emergency-stop
     control.
   - Added a natural-language policy editor below the agent cards.
   - The editor previews server-returned before/after diffs, applies confirmed
     diffs through `POST /policy/apply`, and shows recent `policy_change` audit
     entries without adding a new endpoint.

8. Gate-level transparency
   - Live feed entries and audit log rows show a compact G1/G2/G3/G4 pipeline.
   - Allowed events show all gates passing.
   - Denied events show prior gates passing, the failed gate in red, and later
     gates as neutral.

9. Policy service tests
   - Added dependency-light `unittest` coverage for policy diff validation,
     applicability checks, confirmation enforcement, and applying daily cap
     changes.

### Current Review Gate

The dashboard controls and gate-level transparency are implemented and ready for
review alongside the weighted traffic distribution.

### Remaining Plan

1. Review weighted traffic distribution.
2. Add automated tests around simulator services and dashboard flows.
3. Add production hardening such as auth, migrations, structured logs, and
   concurrency-safe spend commits.

## Architecture

```text
dashboard.html
  |
  | polls
  v
FastAPI backend
  |
  |-- app/routes.py          HTTP endpoints
  |-- app/governance.py      policy and spend decision engine
  |-- app/policy_service.py  natural-language policy parsing and validation
  |-- app/database.py        SQLite audit/state persistence
  |-- app/runtime_state.py   in-memory kill switch and spend cache
  |-- app/config.py          agents, actions, caps, model settings
  |-- app/models.py          Pydantic request/response schemas
  |-- app/simulator.py       background demo traffic
  |
  v
governance.db
```

## Request Flow

Every action submitted to `POST /action` follows this sequence:

1. Check the fleet-wide kill switch.
2. Check whether the agent exists.
3. Check whether the agent has been revoked.
4. Check whether the requested action is allowed for that agent.
5. If the action spends money, validate the amount and spend caps.
6. Commit spend only after approval.
7. Write an audit row for both allowed and denied decisions.

This makes the audit log useful during demos because denial reasons are explicit
and visible in the dashboard.

## Folder Structure

```text
.
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   ├── governance.py
│   ├── models.py
│   ├── policy_service.py
│   ├── routes.py
│   ├── runtime_state.py
│   └── simulator.py
├── dashboard.html
├── frontend/dist/
├── governance.db
├── main.py
├── README.md
├── test_policy_service.py
└── test_policy_endpoints.py
```

## Backend Modules

`main.py`
: FastAPI app entrypoint. Adds CORS, includes routes, initializes the database,
and starts simulated traffic on startup.

`app/config.py`
: Static configuration for demo agents, permitted actions, spend caps, SQLite
path, and Anthropic settings.

`app/models.py`
: Pydantic models for action requests, cap updates, governance decisions, and
natural-language policy changes.

`app/database.py`
: SQLite connection helper, audit log writes, state persistence, and UTC daily
spend-window reset logic.

`app/governance.py`
: Core decision engine. This is the most important policy file. It decides
whether an action is allowed and updates spend after approval.

`app/policy_service.py`
: Converts plain-English policy instructions into structured diffs, validates
them against known agents/actions, and prevents low-confidence or unsafe changes
from being applied.

`app/routes.py`
: HTTP API layer. Route handlers call the governance, database, and policy
services without owning business logic directly.

`app/simulator.py`
: Background task that generates demo traffic every 1.5-3.5 seconds and exposes
the attack simulation sequence used by `POST /simulate-attack`.

## Agent Configuration

Default agents are defined in `app/config.py`:

| Agent | Allowed Actions | Spend Authority |
| --- | --- | --- |
| `payment_agent` | `transfer`, `read_balance` | `$1,000` per transaction, `$5,000` daily |
| `support_agent` | `read_balance`, `create_ticket` | No spend authority |
| `fraud_agent` | `read_balance`, `flag_transaction`, `freeze_account` | No spend authority |

Fleet-wide daily spend cap: `$10,000`.

Spend actions currently include `transfer`.

## Setup

Use Python 3.10+ if available.

```bash
pip install fastapi uvicorn pydantic --break-system-packages
```

The optional policy parsing endpoint also needs outbound network access and:

```bash
export ANTHROPIC_API_KEY=your_api_key_here
```

## Run

From the project root:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

Or:

```bash
python3 main.py
```

The API will be available at:

```text
http://localhost:8000
```

Interactive API docs are available at:

```text
http://localhost:8000/docs
```

## Dashboard

Open `dashboard.html` directly in your browser. It polls:

- `GET /status`
- `GET /agents`
- `GET /feed?limit=15`
- `GET /audit-log?limit=15`

The dashboard shows:

- fleet operational/emergency state
- fleet spend versus fleet cap
- each agent's revoke status
- each agent's allowed actions
- each agent's daily spend
- emergency stop and attack-simulation controls
- natural-language policy preview and apply controls
- recent policy changes from the audit log
- live activity feed
- durable audit log view
- gate-level G1/G2/G3/G4 decision status for feed and audit rows

## API Reference

### Submit Agent Action

```http
POST /action
```

Example:

```json
{
  "agent_id": "payment_agent",
  "action": "transfer",
  "amount": 250,
  "resource": "acct_123"
}
```

Response:

```json
{
  "agent_id": "payment_agent",
  "action": "transfer",
  "allowed": true,
  "reason": "policy checks passed"
}
```

### List Agents

```http
GET /agents
```

Returns agent policy config plus current daily spend.

### Revoke Agent

```http
POST /agents/{agent_id}/revoke
```

Prevents the agent from performing future actions.

### Reinstate Agent

```http
POST /agents/{agent_id}/reinstate
```

Allows a revoked agent to operate again.

### Update Agent Caps

```http
POST /agents/{agent_id}/cap
```

Example:

```json
{
  "per_txn_cap": 500,
  "daily_cap": 2500
}
```

### Emergency Stop

```http
POST /emergency-stop
```

Blocks every agent action fleet-wide.

### Emergency Resume

```http
POST /emergency-resume
```

Disables the fleet-wide emergency stop.

### Fleet Status

```http
GET /status
```

Returns kill switch state, fleet spend, fleet daily cap, and current UTC spend
date.

### Audit Log

```http
GET /audit-log?limit=100
```

Returns persisted audit rows ordered newest-first. `limit` must be between `1`
and `500`.

### Live Feed

```http
GET /feed?limit=20
```

Returns recent audit rows for dashboard display. `limit` must be between `1`
and `100`.

### Simulate Attack

```http
POST /simulate-attack
```

Runs a fixed sequence of risky actions through the same governance function used
by normal agent traffic:

| Agent | Action | Amount | Expected Result |
| --- | --- | ---: | --- |
| `payment_agent` | `transfer` | `$50,000` | Denied by per-transaction cap |
| `payment_agent` | `transfer` | `$25,000` | Denied by per-transaction cap |
| `payment_agent` | `wire_transfer` | `$0` | Denied by action allowlist |
| `support_agent` | `transfer` | `$500` | Denied by action allowlist |
| `fraud_agent` | `transfer` | `$10,000` | Denied by action allowlist |

The endpoint waits about 200ms between each action so the events cascade visibly
in the live dashboard feed.

Example response:

```json
{
  "results": [
    {
      "agent_id": "payment_agent",
      "action": "transfer",
      "amount": 50000,
      "allowed": false,
      "reason": "amount 50000.0 exceeds per-transaction cap 1000.0 for payment_agent"
    }
  ]
}
```

If the emergency stop is active, these actions will be denied for the emergency
stop reason because the kill switch is intentionally evaluated before all other
policy checks.

## Natural-Language Policy Changes

Policy parsing is optional. It lets an operator submit plain English such as:

```text
cut payment_agent's daily cap to $3,000
```

The parse endpoint converts that instruction into a structured diff:

```http
POST /policy/parse
```

Example request:

```json
{
  "instruction": "cut payment_agent's daily cap to $3,000"
}
```

Example response shape:

```json
{
  "diff": {
    "agent_id": "payment_agent",
    "change_type": "update_cap",
    "cap_type": "daily",
    "new_value": 3000,
    "add_actions": null,
    "remove_actions": null,
    "confidence": "high",
    "explanation": "Lower payment_agent's daily cap to $3,000."
  },
  "before": {
    "daily_cap": 5000
  },
  "after": {
    "daily_cap": 3000
  },
  "preview": "payment_agent daily cap: $5,000 -> $3,000",
  "applicable": true,
  "warning": null
}
```

To apply the change:

```http
POST /policy/apply
```

Example request:

```json
{
  "confirmed": true,
  "instruction": "cut payment_agent's daily cap to $3,000",
  "diff": {
    "agent_id": "payment_agent",
    "change_type": "update_cap",
    "cap_type": "daily",
    "new_value": 3000,
    "add_actions": null,
    "remove_actions": null,
    "confidence": "high",
    "explanation": "Lower payment_agent's daily cap to $3,000."
  }
}
```

The server validates the diff again before applying it. It rejects:

- unknown agents
- unknown actions
- missing cap values
- negative or zero natural-language cap changes
- action updates that do not change anything
- low-confidence parses
- unsupported changes like kill switch operations or direct revocations

## Smoke Test Script

`test_policy_endpoints.py` exercises the policy endpoints against a running
server:

```bash
python3 test_policy_endpoints.py
```

Without `ANTHROPIC_API_KEY`, it still tests server-side validation for bad
policy diffs. With the key set, it also tests parse examples.

## Demo Script

1. Start the backend.
2. Open `dashboard.html`.
3. Let simulated traffic run for 10 seconds.
4. Point out an allowed transfer and a denied transfer, including how the gate
   pipeline lights up green for allowed actions and stops red at the failing
   gate for denied actions.
5. Revoke `payment_agent`.
6. Watch its future actions get denied.
7. Trigger emergency stop.
8. Watch all agents get denied with the fleet-wide stop reason.
9. Resume the fleet.
10. Click the Simulate Attack button near the emergency control.
11. Watch the five denied attack actions cascade into the feed and audit log,
    with the gate pipeline stopping at the relevant failed gate.
12. Type a plain-English policy change into the policy editor, click Preview
    Change, review the server-returned before/after diff, then click Confirm &
    Apply.
13. Watch the policy change appear under Recent Policy Changes and in the audit
    log.
14. Open `/docs` and show the governed API surface.

## Production Hardening Ideas

This demo is now organized for growth, but a real production version should add:

- authentication and role-based authorization for operator endpoints
- stricter CORS configuration instead of `allow_origins=["*"]`
- durable policy storage instead of in-memory agent config
- database migrations
- request IDs and structured logs
- metrics for allowed/denied decisions and policy changes
- idempotency keys for action execution
- optimistic locking or transactions around spend commits under concurrency
- proper test suite with `pytest` and `httpx`
- deployment config and environment-based settings
- OPA/Rego or another formal policy engine if policies become complex

## Verification

Useful local checks:

```bash
PYTHONPYCACHEPREFIX=/private/tmp/code-street-pycache python3 -m py_compile main.py app/*.py test_policy_endpoints.py
```

```bash
curl http://127.0.0.1:8000/status
```

```bash
curl -X POST http://127.0.0.1:8000/action \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"payment_agent","action":"transfer","amount":50,"resource":"acct_demo"}'
```

```bash
curl -X POST http://127.0.0.1:8000/simulate-attack
```
