"""Runtime state for kill switch and spend windows."""

from app.config import AGENTS, utc_today

STATE = {
    "kill_switch": False,
    "agent_spend_today": {aid: 0.0 for aid in AGENTS},
    "fleet_spend_today": 0.0,
    "spend_date": utc_today(),
}
