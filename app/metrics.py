"""Metrics tracking for Prometheus and benchmarking."""

import time
from collections import defaultdict

# Global metrics storage
METRICS = {
    "evaluations_total": defaultdict(int),  # e.g. ("allowed", "reason") -> count
    "status_counts": {"allowed": 0, "denied": 0},
    "latencies_us": [],  # Store recent latency samples in microseconds
    "max_samples": 5000,
}


def record_evaluation(allowed: bool, reason: str, duration_us: float):
    status = "allowed" if allowed else "denied"
    METRICS["status_counts"][status] += 1
    METRICS["evaluations_total"][(status, reason)] += 1
    
    # Store latency sample
    METRICS["latencies_us"].append(duration_us)
    if len(METRICS["latencies_us"]) > METRICS["max_samples"]:
        METRICS["latencies_us"] = METRICS["latencies_us"][-2000:]


def get_prometheus_metrics(kill_switch_active: bool, fleet_spend: float, fleet_cap: float) -> str:
    lines = [
        "# HELP governance_evaluations_total Total number of governance policy evaluations",
        "# TYPE governance_evaluations_total counter",
        f'governance_evaluations_total{{status="allowed"}} {METRICS["status_counts"]["allowed"]}',
        f'governance_evaluations_total{{status="denied"}} {METRICS["status_counts"]["denied"]}',
        "",
        "# HELP governance_emergency_stop_status Fleet emergency stop status (1 = active, 0 = inactive)",
        "# TYPE governance_emergency_stop_status gauge",
        f'governance_emergency_stop_status {1 if kill_switch_active else 0}',
        "",
        "# HELP governance_fleet_spend_today_usd Total spend today across all agents in USD",
        "# TYPE governance_fleet_spend_today_usd gauge",
        f'governance_fleet_spend_today_usd {fleet_spend}',
        "",
        "# HELP governance_fleet_daily_cap_usd Total fleet daily spend cap in USD",
        "# TYPE governance_fleet_daily_cap_usd gauge",
        f'governance_fleet_daily_cap_usd {fleet_cap}',
    ]

    if METRICS["latencies_us"]:
        avg_lat = sum(METRICS["latencies_us"]) / len(METRICS["latencies_us"])
        sorted_lat = sorted(METRICS["latencies_us"])
        p50 = sorted_lat[int(len(sorted_lat) * 0.5)]
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)]
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)]

        lines.extend([
            "",
            "# HELP governance_evaluation_latency_microseconds Policy evaluation latency in microseconds",
            "# TYPE governance_evaluation_latency_microseconds summary",
            f'governance_evaluation_latency_microseconds{{quantile="0.5"}} {p50:.2f}',
            f'governance_evaluation_latency_microseconds{{quantile="0.95"}} {p95:.2f}',
            f'governance_evaluation_latency_microseconds{{quantile="0.99"}} {p99:.2f}',
            f'governance_evaluation_latency_microseconds_sum {sum(METRICS["latencies_us"]):.2f}',
            f'governance_evaluation_latency_microseconds_count {len(METRICS["latencies_us"])}',
        ])

    return "\n".join(lines) + "\n"
