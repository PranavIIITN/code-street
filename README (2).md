# Fleet Governance Layer — Demo

## Run the backend
```bash
pip install fastapi uvicorn --break-system-packages
cd governance-backend
uvicorn main:app --host 0.0.0.0 --port 8000
```
This starts the API on `http://localhost:8000` and immediately begins firing
simulated agent traffic every 1.5–3.5s in the background, so the dashboard
has live data without anyone clicking anything.

## Open the dashboard
Just open `dashboard.html` directly in a browser (double-click it, or
`open dashboard.html` / drag into a browser tab). It polls the backend
every 1.5s — no build step, no npm install.

## What to demo (suggested order)
1. **Let it sit for ~10s** — show the live feed populating on its own
   (simulated agents doing transfers, balance checks, ticket creation).
2. **Point out a denied action** in the feed — e.g. an amount that
   exceeded a cap, or an action outside an agent's permission scope —
   and read the `reason` string out loud. This is your "auditability" proof.
3. **Hit "Revoke agent"** on payment_agent — show its next simulated
   action get denied with reason "has been revoked."
4. **Hit the big red STOP button** — show every agent's next action
   getting denied fleet-wide. This is your best visual moment — let it
   run for a few seconds so multiple agents visibly get blocked.
5. **Hit RESUME** — show it return to normal.
6. **Scroll the audit log** — point out every decision (allow/deny) is
   permanently recorded with a timestamp and reason.

## Key endpoints (for reference / Postman / curl demo)
- `POST /action` — submit an agent action `{agent_id, action, amount, resource}`
- `GET /agents` — list agents + their live spend
- `POST /agents/{id}/revoke` / `/reinstate`
- `POST /agents/{id}/cap` — update `{per_txn_cap, daily_cap}`
- `POST /emergency-stop` / `/emergency-resume`
- `GET /audit-log?limit=100`
- `GET /status` — kill switch + fleet spend

## Notes for the deck
- Policy logic (`evaluate_action` in `main.py`) is written to mirror what a
  real OPA/Rego policy would encode — described as "simplified for hackathon
  speed" if asked, with `policy.rego` (ask me to generate this next) as the
  production-equivalent reference.
- Spend caps operate at 3 levels: per-transaction, per-agent-daily, and
  fleet-wide-daily — all enforced before the action is allowed to execute.
- Kill switch and revocation checks run *before* any policy/spend logic,
  so they're O(1) and unaffected by the complexity of other checks.
