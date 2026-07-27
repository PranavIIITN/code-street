# Fleet Governance Layer for Financial Agents
> **Submission Documentation & Presentation Guide**

---

## 1. Executive Summary & Project Description

As autonomous AI agents proliferate across banking, trading, and automated financial operations, exposing core financial infrastructure directly to autonomous decision-makers creates systemic risk. Without central guardrails, a rogue or compromised agent could trigger runaway transactions, exhaust daily capital reserves, or bypass organizational compliance.

**Fleet Governance Layer** is a lightweight, ultra-low-latency governance infrastructure designed for banks and enterprise financial institutions. Every financial agent action passes through a centralized, high-throughput decision engine prior to execution. The engine evaluates actions in real time against global emergency controls, agent-specific permissions, multi-tier daily spend caps, attribute-based access rules (ABAC), and dynamic policy diffs—logging every allowed and denied decision with full gate-level transparency.

---

## 2. Core Capabilities & Task Alignment

| Challenge Requirement | Implementation in Fleet Governance Layer |
| :--- | :--- |
| **1. Granular Permission Model & ABAC** | Per-agent action allowlists (`payment_transfer`, `portfolio_rebalance`, `trade_execution`, `data_query`), resource target scoping (`allowed_resources`), and risk score thresholds (`max_risk_score`). |
| **2. Dynamic Spend Caps & Limits** | Multi-layer real-time spend controls: Per-transaction cap, Per-agent daily cap, and Fleet-wide daily cap (`FLEET_DAILY_CAP`). Enforces non-negative spend validation and automatic UTC date spend window resets. |
| **3. Revocation & Emergency Stop** | Instant single-click fleet-wide **Emergency Stop** kill switch (`POST /emergency-stop`) and per-agent **Revoke / Reinstate** toggles. Persistence ensures kill-switch state survives server restarts. |
| **4. Operator Dashboard & Audit Log** | Live interactive browser dashboard displaying real-time agent metrics, gate-by-gate decision transparency, interactive spend sliders, instant audit log streaming, and **Audit CSV Exporter** (`/audit-log/export`). |
| **5. Low Latency & Security Testing** | Sub-millisecond policy evaluation time. Includes an integrated **Simulated Attack Engine** (`POST /simulate-attack`) and a built-in **1,000-eval Benchmark Engine** (`POST /benchmark`) for real-time throughput & latency proof. |
| **6. Monitoring & OPA Policy Export** | Standard **Prometheus Exporter** (`GET /metrics`) for Grafana/Splunk monitoring and dynamic **Open Policy Agent (.rego) Policy Exporter** (`GET /policy/export`). |
| **Bonus: Natural Language Policy AI** | Natural-language policy parser (`POST /policy/parse` & `/policy/apply`) that translates plain-English instructions into validated JSON policy diffs before operator confirmation. |

---

## 3. System Architecture & Evaluation Pipeline

```
                     +---------------------------------------+
                     |  Autonomous Financial Agents (Fleet)  |
                     +---------------------------------------+
                                         |
                                         v
                         POST /action (Payload Request)
                                         |
                     +---------------------------------------+
                     |    Fleet Governance Decision Engine   |
                     +---------------------------------------+
                                         |
         +-------------------------------+-------------------------------+
         |                               |                               |
 [Gate 1: Emergency Stop]     [Gate 2: Revocation Check]    [Gate 3: Action Allowlist]
         |                               |                               |
 [Gate 4: Resource ABAC]      [Gate 5: Risk Threshold]     [Gate 6: Negative Spend]
         |                               |                               |
 [Gate 7: Tx Cap Check]       [Gate 8: Agent Daily Cap]    [Gate 9: Fleet Daily Cap]
                                         |
                                         v
                       +-----------------------------------+
                       |  Result: ALLOWED / DENIED          |
                       |  + Audit Log Entry (SQLite DB)    |
                       |  + Prometheus Metrics Exporter    |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       |  Live Operator Dashboard (React)  |
                       +-----------------------------------+
```

---

## 4. API Endpoints Reference

### Core Governance Endpoints
- `POST /action` — Evaluates agent request against the 9-stage policy pipeline (including risk score and target resource).
- `GET /agents` — Returns current status, spend, caps, and revocation state for all fleet agents.
- `POST /agents/{agent_id}/revoke` — Instantly revokes permissions for a specific agent.
- `POST /agents/{agent_id}/reinstate` — Reinstates a revoked agent.
- `POST /agents/{agent_id}/cap` — Updates per-agent transaction and daily budget caps dynamically.
- `POST /emergency-stop` — Triggers a fleet-wide emergency halt on all agent actions.
- `POST /resume-fleet` — Resets fleet emergency status back to active.
- `GET /audit-log` — Fetches complete, timestamped history of governance decisions.
- `GET /audit-log/export` — Downloads audit log in CSV format for regulatory compliance.
- `GET /metrics` — Exposes Prometheus text metrics for Prometheus, Grafana, and Splunk ingest.
- `POST /benchmark` — Executes a 1,000-policy evaluation latency test returning throughput QPS and p50/p95/p99 metrics.
- `GET /policy/export` — Exports current governance rules as Open Policy Agent (OPA) `.rego` policy code.
- `POST /simulate-attack` — Injects a sequence of 5 rogue/anomalous agent actions to demonstrate governance defenses.
- `POST /policy/parse` & `POST /policy/apply` — AI-assisted natural-language policy creation and diff application.

---

## 5. Presentation & Pitch Deck Outline (Slide-by-Slide)

### Slide 1: Title & Problem Statement
- **Title**: Fleet Governance Layer — Trust Infrastructure for Autonomous Financial AI
- **Problem**: Financial institutions are deploying fleets of AI agents for trading, transfers, and portfolio management. Without real-time guardrails, bugs or adversarial attacks can trigger catastrophic financial loss in milliseconds.

### Slide 2: The Solution
- **Centralized Safety Gateway**: Every agent request is authorized through a single zero-trust control plane before reaching core banking APIs.
- **9-Stage Policy Engine**: Multi-tiered protection covering emergency stops, action allowlists, ABAC resource checks, risk thresholds, per-transaction caps, agent daily budgets, and fleet limits.

### Slide 3: Live Governance & Real-Time Controls
- **Instant Kill Switches**: Fleet-wide emergency stop and per-agent instant revocation.
- **Dynamic Cap Management**: Adjust spending thresholds on the fly without service redeployment.
- **Auditability & Observability**: Prometheus metrics exporter (`/metrics`), dynamic OPA (.rego) policy export, and CSV audit log downloads.

### Slide 4: Real-World Demonstration & Attack Resilience
- **Simulated Attack Mode**: Shows live blocking of unauthorized data queries, negative spend exploits, and budget overruns.
- **Benchmark Suite**: Proven sub-millisecond evaluation latency (< 0.5ms) across 1,000+ QPS.
- **Natural-Language Policy Management**: Demonstrates AI translating plain English (e.g., *"Lower Payment Agent transaction limit to $500"*) into validated policy diffs.

### Slide 5: Performance & Technical Excellence
- **Ultra-Low Latency**: Lightweight FastAPI engine with microsecond policy evaluation time.
- **Enterprise Standards**: OPA (.rego) compliance, Prometheus/Grafana export readiness, and persistent SQLite audit storage.

---

## 6. Live Deployment Link & Demo Checklist

- **Live URL**: `https://code-street-fhpg.onrender.com`
- **Dashboard**: Accessible directly at the root domain (`/`).
- **Video Demo Walkthrough Guide**:
  1. Open the Live Dashboard.
  2. Show live agent traffic running smoothly.
  3. Click **⚡ Run 1k Benchmark** to demonstrate sub-millisecond evaluation speed and QPS to the judges.
  4. Click **📊 Prometheus Metrics** and **🛡️ OPA Rego Export** to show enterprise integration capabilities.
  5. Click **Simulate Attack** to watch the governance layer detect and deny malicious attempts in real-time.
  6. Click **Emergency Stop** to demonstrate total fleet shutdown.
  7. Use the Natural-Language Policy box to type a policy change (e.g., *"Revoke Support Agent"*), preview the diff, and click Apply.
