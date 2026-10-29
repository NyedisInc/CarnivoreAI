from __future__ import annotations

METRICS = {
    "input_tokens": ("tokens", "minute_usage"),
    "cache_write_tokens": ("tokens", "minute_usage"),
    "cache_read_tokens": ("tokens", "minute_usage"),
    "output_tokens": ("tokens", "minute_usage"),
    "total_tokens": ("tokens", "minute_usage"),
    "estimated_cost_nano_usd": ("nano_usd", "minute_usage"),
    "usage_count": ("observations", "minute_usage"),
    "observed_seconds": ("seconds", "activity_minutes"),
    "working_seconds": ("seconds", "activity_minutes"),
    "running_seconds": ("seconds", "activity_minutes"),
    "starts": ("events", "activity_minutes"),
    "completions": ("events", "activity_minutes"),
    "waiting_seconds": ("seconds", "activity_minutes"),
    "subagent_seconds": ("seconds", "activity_minutes"),
    "average_working_agents": ("agents", "activity_minutes"),
    "average_running_agents": ("agents", "activity_minutes"),
    "quota_utilization": ("percent", "quota_minutes"),
    "tool_calls": ("events", "minute_counters"),
    "stop_reasons": ("events", "minute_counters"),
    "thinking_tokens": ("tokens", "minute_counters"),
    "web_searches": ("events", "minute_counters"),
    "web_fetches": ("events", "minute_counters"),
    "compactions": ("events", "minute_counters"),
    "turns": ("events", "minute_counters"),
    "cache_write_5m_tokens": ("tokens", "minute_counters"),
    "cache_write_1h_tokens": ("tokens", "minute_counters"),
}
DIMENSIONS = ("host", "provider", "project", "model", "agent_kind", "conversation_id", "account_id", "window")
RESOLUTIONS = ("minute", "5minute", "hour", "day", "week", "month", "year")


def catalog() -> dict:
    return {
        "metrics": [
            {"id": key, "unit": unit, "operations": ["summary", "timeline", "ranking", "comparison"],
             "transforms": (["total"] if key in ("quota_utilization", "average_working_agents",
                                                "average_running_agents") else
                            ["total", "rate", "cumulative", "per_conversation"]),
             "group_by": list(("account_id", "window", "provider") if table == "quota_minutes"
                              else (*DIMENSIONS[:6], "key") if table == "minute_counters"
                              else DIMENSIONS[:6]),
             "estimate": key == "estimated_cost_nano_usd"}
            for key, (unit, table) in METRICS.items()
        ],
        "resolutions": ["auto", *RESOLUTIONS],
        "limits": {"points": 600, "expanded_series": 12, "top_n": 10, "contributions_page": 200},
        "transforms": ["total", "rate", "cumulative", "per_conversation"],
        "price_basis": "Versioned repository list-rate estimate applied to recorded usage; unknown pricing is null.",
    }
