
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from src.core.crate_format.reader import CrateReader
from src.core.crate_import import keymap, policy, validate
from src.core.crate_import.env import ImportEnv
from src.core.crate_import.model import (
    B_BAD_IDENTIFIER, B_PATH_OUTSIDE_SCOPE, W_OUTSIDE_MAPPING, Collector,
)
from src.core.crate_import.provenance import Provenance
from src.core.crate_import.session_plan import SessionPlan
from src.core.inventory import registry
from src.core.inventory.claims import ClaimBook
from src.core.inventory.model import MAIN_STORE
from src.core.project_move.paths import PathMapping

SAMPLE_ROWS = 1


@dataclass
class RowsPlan:

    rows: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    rewrites: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dropped: Dict[str, str] = field(default_factory=dict)
    not_restored: List[Dict[str, str]] = field(default_factory=list)
    sessions: List[Dict[str, Any]] = field(default_factory=list)
    project_rows: List[Dict[str, Any]] = field(default_factory=list)
    sanitized: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    skipped_sessions: Dict[str, str] = field(default_factory=dict)
    skip_reasons: Dict[str, int] = field(default_factory=dict)


def _claim_facts(book: ClaimBook, label: str, table: str) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    secret: List[str] = []
    paths: List[str] = []
    for claim in book.claims_for(label, table):
        secret += [c for c in claim.secret if c not in secret]
        paths += [c for c in claim.paths if c not in paths]
    return tuple(secret), tuple(paths)


def _note(plan: RowsPlan, key: str, verdict: validate.RowVerdict) -> None:
    for column, reason in verdict.dropped.items():
        plan.dropped.setdefault(f"{key}.{column}", reason)
    for column, old, new in verdict.rewrites:
        entry = plan.rewrites.setdefault(f"{key}.{column}", {"count": 0, "sample_from": old, "sample_to": new})
        entry["count"] += 1


def plan_rows(reader: CrateReader, env: ImportEnv, conn: sqlite3.Connection, mapping: PathMapping, prov: Provenance,
              source_install: Optional[str], col: Collector, book: Optional[ClaimBook] = None,
              sessions: Optional[SessionPlan] = None) -> RowsPlan:
    book = book or registry.book()
    plan = RowsPlan()
    maps = keymap.KeyMaps(conn, source_install)
    with keymap.LocalTables(env, conn) as local:
        for crate_store, by_name in reader.tables().items():
            for table, record in by_name.items():
                label = record.inventory_label
                key = f"{label}.{table}"
                decision = policy.decision_for(book, label, table)
                if decision is None:
                    plan.rows[key] = {"insert": 0, "present": 0, "kept_local": 0, "skipped": record.rows, "reason": policy.NOT_RESTORED}
                    plan.not_restored.append({"what": key, "why": policy.NOT_RESTORED})
                    continue
                if not decision.writes:
                    plan.rows[key] = {"insert": 0, "present": 0, "kept_local": 0, "skipped": record.rows,
                                      "reason": decision.reason or decision.kind}
                    if decision.kind == policy.SKIP:
                        plan.not_restored.append({"what": key, "why": decision.reason})
                    continue
                if not policy.applied(label, table):
                    plan.rows[key] = {"insert": 0, "present": 0, "kept_local": 0, "skipped": record.rows, "reason": policy.NOT_YET}
                    plan.not_restored.append({"what": key, "why": policy.NOT_YET})
                    continue
                secret, paths = _claim_facts(book, label, table)
                shape = validate.live_shape(conn, table) if label == MAIN_STORE else None
                if label == MAIN_STORE and shape is None:
                    plan.rows[key] = {"insert": 0, "present": 0, "kept_local": 0, "skipped": record.rows, "reason": "table_absent_here"}
                    plan.not_restored.append({"what": key, "why": "table_absent_here"})
                    continue
                prior = keymap.prior_for(conn, source_install, label, table)
                counts = {"insert": 0, "present": 0, "kept_local": 0, "skipped": 0}
                for row in reader.rows(crate_store, table):
                    verdict = validate.sanitize_row(table, row, shape=shape, secret_columns=secret, path_columns=paths,
                                                    mapping=mapping, provenance=prov, store=label)
                    _note(plan, key, verdict)
                    if verdict.row is not None and sessions is not None:
                        why = sessions.skip_reason(label, table, verdict.row)
                        if why is not None:
                            counts["skipped"] += 1
                            plan.skip_reasons[why] = plan.skip_reasons.get(why, 0) + 1
                            continue
                        sessions.translate_row(label, table, verdict.row)
                    if verdict.bad_identifier:
                        col.block(B_BAD_IDENTIFIER, f"{key}.{','.join(verdict.bad_identifier)}")
                    for column in verdict.path_blocks:
                        col.block(B_PATH_OUTSIDE_SCOPE, f"{key}.{column}")
                    if verdict.outside and not verdict.path_blocks:
                        col.warn(W_OUTSIDE_MAPPING, f"{key}.{verdict.outside[0]}")
                    if verdict.row is None:
                        counts["skipped"] += 1
                        if key == f"{MAIN_STORE}.sessions" and verdict.skipped and row.get("session_uuid"):
                            plan.skipped_sessions[str(row["session_uuid"])] = verdict.skipped
                        continue
                    plan.sanitized.setdefault(key, []).append(verdict.row)
                    counts[keymap.classify_row(local, label, table, verdict.row, prior, maps)] += 1
                    if key == f"{MAIN_STORE}.sessions":
                        plan.sessions.append(verdict.row)
                    elif key == f"{MAIN_STORE}.projects":
                        plan.project_rows.append(verdict.row)
                plan.rows[key] = counts
    return plan
