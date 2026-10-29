from __future__ import annotations

import hashlib
import random
import sqlite3
import statistics
import time

from src.core.session_token_usage.model_table import readable_model_name
from src.core.stats import config
from src.core.stats import project_groups
from src.core.stats.project_groups import other_label
from src.core.stats.queries import (
    DEADLINE_SECONDS, MAX_ROWS, QueryLimit,
    _usage_source, _where,
)
from src.models.stats import StatsFilters

CONVERSATION_CAP = 500
"""Most conversations the scatter returns (the costliest, then the largest)."""
BOOTSTRAP_ITERATIONS = 1000
"""Resamples of the impact confidence interval; fixed so the cost of a read is bounded."""
SAMPLE_CAP = 1000
"""Most conversations resampled per side; a larger side is subsampled with the same seeded generator."""
MIN_SAMPLES = 5
"""Fewest conversations a side needs before a change is claimed at all."""
MIX_SHIFT = 0.25
"""Total variation distance between the two model mixes at which the mix is called shifted."""
_METRIC_SQL = {
    "total_tokens": "SUM(input_tokens+cache_write_tokens+cache_read_tokens+output_tokens)",
    "input_tokens": "SUM(input_tokens)", "output_tokens": "SUM(output_tokens)",
    "cache_read_tokens": "SUM(cache_read_tokens)", "usage_count": "SUM(usage_count)",
    "estimated_cost_nano_usd": "SUM(estimated_cost_nano_usd)",
}
_UNITS = {"estimated_cost_nano_usd": "nano_usd", "usage_count": "observations"}


def _grouped(store, filters: StatsFilters, start: int, end: int, metric: str) -> list[sqlite3.Row]:
    deadline = time.monotonic() + DEADLINE_SECONDS
    where, args = _where("minute_usage", filters, start, end)
    source = _usage_source(filters, None)
    db = store.connect(readonly=True)
    try:
        db.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 1000)
        rows = db.execute(
            f"SELECT conversation_id,project,model,{_METRIC_SQL[metric]} AS value,"
            "SUM(input_tokens+cache_write_tokens+cache_read_tokens+output_tokens) AS tokens,"
            "MIN(minute_ts) AS first_ts,MAX(minute_ts) AS last_ts "
            f"FROM {source} WHERE {where} GROUP BY conversation_id,project,model "
            "ORDER BY conversation_id,project,model LIMIT ?", (*args, MAX_ROWS + 1)).fetchall()
        if len(rows) > MAX_ROWS:
            raise QueryLimit("query exceeds row budget; narrow the range")
        return rows
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc):
            raise QueryLimit("query deadline exceeded") from exc
        raise
    finally:
        db.close()


def _per_conversation(rows: list[sqlite3.Row]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for row in rows:
        entry = out.setdefault(row["conversation_id"], {"value": None, "tokens": 0, "first": row["first_ts"],
                                                         "last": row["last_ts"], "top": -1,
                                                         "project": row["project"], "model": row["model"]})
        if row["value"] is not None:
            entry["value"] = (entry["value"] or 0) + row["value"]
        entry["tokens"] += row["tokens"]
        entry["first"] = min(entry["first"], row["first_ts"])
        entry["last"] = max(entry["last"], row["last_ts"])
        if row["tokens"] > entry["top"]:
            entry["top"], entry["project"], entry["model"] = row["tokens"], row["project"], row["model"]
    return out


def conversations(store, *, start: int, end: int, filters: StatsFilters, limit: int = CONVERSATION_CAP) -> dict:
    limit = max(1, min(limit, CONVERSATION_CAP))
    grouped = _per_conversation(_grouped(store, filters, start, end, "estimated_cost_nano_usd"))
    ordered = sorted(grouped.items(), key=lambda pair: (pair[1]["value"] is None, -(pair[1]["value"] or 0),
                                                        -pair[1]["tokens"], pair[0]))[:limit]
    ids = [conversation for conversation, _ in ordered]
    meta: dict[str, tuple[int | None, int | None]] = {}
    if ids:
        with store.connect(readonly=True) as db:
            marks = ",".join("?" * len(ids))
            meta = {row[0]: (row[1], row[2]) for row in db.execute(
                f"SELECT conversation_id,first_minute,last_minute FROM conversation_meta WHERE conversation_id IN ({marks})", ids)}
    groups = project_groups.groups_for(store) if ids else None
    items = []
    for conversation, entry in ordered:
        first, last = meta.get(conversation, (None, None))
        first = entry["first"] if first is None else first
        last = entry["last"] if last is None else last
        items.append({
            "conversation_id": conversation,
            "project": groups.conversation_label(entry["project"]) if groups else other_label(1),
            "model": entry["model"], "model_label": readable_model_name(entry["model"]) or None,
            "tokens": entry["tokens"], "cost_nano_usd": entry["value"],
            "first_minute": first, "last_minute": last, "duration_seconds": max(60, last - first + 60),
        })
    return {"items": items, "total": len(grouped), "truncated": len(grouped) > limit, "unit": "nano_usd"}


def _seed(annotation_id: str, metric: str, days: int) -> int:
    return int(hashlib.sha256(f"{annotation_id}:{metric}:{days}".encode()).hexdigest()[:8], 16)


def _bootstrap(before: list[float], after: list[float], seed: int, iterations: int) -> tuple[float, float]:
    rng = random.Random(seed)
    diffs = sorted(statistics.median(rng.choices(after, k=len(after))) - statistics.median(rng.choices(before, k=len(before)))
                   for _ in range(iterations))
    return diffs[int(0.025 * iterations)], diffs[max(0, int(0.975 * iterations) - 1)]


def _mix(rows: list[sqlite3.Row], per: dict[str, dict], cut: int) -> tuple[dict[str, int], dict[str, int]]:
    sides: tuple[dict[str, int], dict[str, int]] = ({}, {})
    for row in rows:
        side = sides[0] if per[row["conversation_id"]]["first"] < cut else sides[1]
        side[row["model"]] = side.get(row["model"], 0) + row["tokens"]
    return sides


def _mix_report(before: dict[str, int], after: dict[str, int]) -> dict:
    total_before, total_after = sum(before.values()), sum(after.values())
    if not total_before or not total_after:
        return {"distance": None, "shifted": False, "models": []}
    names = sorted(set(before) | set(after))
    moves = [{"model": name, "model_label": readable_model_name(name) or None,
              "before": before.get(name, 0) / total_before, "after": after.get(name, 0) / total_after}
             for name in names]
    distance = 0.5 * sum(abs(move["after"] - move["before"]) for move in moves)
    moves.sort(key=lambda move: (-abs(move["after"] - move["before"]), move["model"]))
    return {"distance": distance, "shifted": distance >= MIX_SHIFT, "models": moves[:3]}


def impact(store, *, annotation_id: str, metric: str, days: int, now: float | None = None,
           iterations: int = BOOTSTRAP_ITERATIONS) -> dict:
    if metric not in _METRIC_SQL or not 1 <= days <= 30:
        raise ValueError("unsupported impact metric or window")
    marker = config.get_annotation(store, annotation_id)
    now = time.time() if now is None else now
    at = int(marker["occurred_at"])
    if at >= now:
        raise ValueError("the marker has not happened yet")
    start, end = at - days * 86400, min(at + days * 86400, int(now) // 60 * 60 + 60)
    scope = {key: value for key, value in marker["scope"].items() if key != "window"}
    filters = StatsFilters.model_validate(scope)
    rows = _grouped(store, filters, start, end, metric)
    per = _per_conversation(rows)
    samples: tuple[list[float], list[float]] = ([], [])
    counts = [0, 0]
    for _, entry in sorted(per.items()):
        side = 0 if entry["first"] < at else 1
        counts[side] += 1
        if entry["value"] is not None:
            samples[side].append(float(entry["value"]))
    seed = _seed(annotation_id, metric, days)
    capped = [side if len(side) <= SAMPLE_CAP else random.Random(seed).sample(side, SAMPLE_CAP) for side in samples]
    medians = [statistics.median(side) if side else None for side in samples]
    enough = all(len(side) >= MIN_SAMPLES for side in samples)
    interval = _bootstrap(capped[0], capped[1], seed, iterations) if enough else None
    delta = None if medians[0] is None or medians[1] is None else medians[1] - medians[0]
    verdict = ("insufficient" if interval is None else "higher" if interval[0] > 0
               else "lower" if interval[1] < 0 else "no_clear_change")
    mix = _mix_report(*_mix(rows, per, at))
    return {
        "annotation": {"id": marker["id"], "label": marker["label"], "kind": marker["kind"],
                       "reference": marker["reference"], "occurred_at": at},
        "metric": metric, "unit": _UNITS.get(metric, "tokens"), "days": days,
        "before": {"from": start, "to": at, "n": len(samples[0]), "conversations": counts[0], "median": medians[0]},
        "after": {"from": at, "to": end, "n": len(samples[1]), "conversations": counts[1], "median": medians[1],
                  "partial": end - at < days * 86400 - 60},
        "delta": {"absolute": delta, "percent": (delta / medians[0]) if delta is not None and medians[0] else None},
        "interval": None if interval is None else {"low": interval[0], "high": interval[1], "level": 0.95,
                                                    "iterations": iterations, "seed": seed},
        "mix": mix, "verdict": verdict,
        "subsampled": any(len(side) > SAMPLE_CAP for side in samples),
    }
