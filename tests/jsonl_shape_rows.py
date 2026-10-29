
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional, Tuple

from tests.jsonl_shape_support import (
    agent_id_form,
    body_dimensions,
    key_order_digest,
    no_body_dimensions,
    signature_id,
    NULL_TOKEN,
    _envelope_keys,
    _key_order_len,
)

APPEARANCE_JOIN_SQL: str = (
    "SELECT a.id, a.transcript_id, a.line_no, a.line_status, "
    "       a.serializer_style, a.raw_line, a.body_id, a.envelope_json, "
    "       a.key_order_json, a.fidelity_outcome, a.is_sidechain, "
    "       a.agent_id, a.line_sha256, a.line_byte_length, "
    "       t.line_ending, t.has_trailing_newline, "
    "       b.body_json, b.is_compact_boundary, b.parent_uuid, b.ts, "
    "       b.message_uuid, rt.value, ro.value, mo.value, cs.value "
    "FROM message_appearances a "
    "JOIN message_transcripts t ON t.id = a.transcript_id "
    "LEFT JOIN message_bodies b ON b.id = a.body_id "
    "LEFT JOIN message_record_types rt ON rt.id = b.record_type_id "
    "LEFT JOIN message_roles ro ON ro.id = b.role_id "
    "LEFT JOIN message_models mo ON mo.id = b.model_id "
    "LEFT JOIN message_compact_subtypes cs ON cs.id = b.compact_subtype_id "
)

BY_COORDINATE_SQL: str = (
    APPEARANCE_JOIN_SQL + "WHERE a.transcript_id = ? AND a.line_no = ?"
)

ABOVE_WATERMARK_SQL: str = (
    APPEARANCE_JOIN_SQL + "WHERE a.id > ? ORDER BY a.id"
)


def row_to_dict(row: Tuple[Any, ...]) -> Dict[str, Any]:
    names = (
        "appearance_id", "transcript_id", "line_no", "line_status",
        "serializer_style", "raw_line", "body_id", "envelope_json",
        "key_order_json", "fidelity_outcome", "is_sidechain", "agent_id",
        "line_sha256", "line_byte_length", "line_ending",
        "has_trailing_newline", "body_json", "is_compact_boundary",
        "parent_uuid", "ts", "message_uuid", "record_type", "role", "model",
        "compact_subtype",
    )
    return dict(zip(names, row))


def dimensions_for_row(row: Dict[str, Any]) -> Dict[str, Any]:
    if row["body_id"] is None:
        body_dims = no_body_dimensions()
    else:
        body_dims = body_dimensions(
            json.loads(row["body_json"]), row["record_type"], row["role"],
            row["model"], row["compact_subtype"],
            row["is_compact_boundary"], row["parent_uuid"], row["ts"],
            row["message_uuid"],
        )
    dims: Dict[str, Any] = {
        "line_status": row["line_status"],
        "serializer_style": row["serializer_style"] or NULL_TOKEN,
        "render_source": "raw" if row["raw_line"] is not None else "rendered",
        "body_row": "body" if row["body_id"] is not None else "nobody",
        "envelope_keys": _envelope_keys(row["envelope_json"]),
        "key_order_digest": key_order_digest(row["key_order_json"]),
        "key_order_len": _key_order_len(row["key_order_json"]),
        "is_sidechain": int(row["is_sidechain"]),
        "agent_id_form": agent_id_form(row["agent_id"]),
        "fidelity_outcome": row["fidelity_outcome"],
        "line_ending": row["line_ending"],
        "has_trailing_newline": int(row["has_trailing_newline"]),
    }
    dims.update(body_dims)
    return dims


def signature_for_row(row: Dict[str, Any]) -> str:
    return signature_id(dimensions_for_row(row))


def fetch_exemplar(
    conn: sqlite3.Connection, transcript_id: int, line_no: int,
) -> Optional[Dict[str, Any]]:
    row = conn.execute(BY_COORDINATE_SQL, (transcript_id, line_no)).fetchone()
    return None if row is None else row_to_dict(row)
