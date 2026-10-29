
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

CORPUS_DB_ENV_VAR: str = "CLOUDE_FIDELITY_DB"

DEFAULT_CORPUS_DB: str = (
    "/Users/sam/Scratch/scratch-lab/cc-dev-state/cloude.db"
)

REPO_ROOT: Path = Path(__file__).resolve().parent.parent

MANIFEST_PATH: Path = REPO_ROOT / "tests" / "fixtures" / "jsonl_shape_manifest.json"

SUPPORTED_MANIFEST_SCHEMA_VERSION: int = 1

SIGNATURE_ID_HEX_CHARS: int = 24
KEY_ORDER_DIGEST_HEX_CHARS: int = 16

KEY_ORDER_NULL_SENTINEL: str = "\x00<NULL>"

NULL_TOKEN: str = "<NULL>"
UNPARSEABLE_TOKEN: str = "<UNPARSEABLE>"
NO_BODY_TOKEN: str = "<no body>"
NO_MESSAGE_TOKEN: str = "<no message obj>"
ABSENT_TOKEN: str = "<absent>"
NON_STRING_TOKEN: str = "<non-str>"
NON_STRING_TYPE_TOKEN: str = "<non-str type>"

AGENT_ID_PREFIXES: Tuple[str, ...] = ("agent:", "agent-")

BODY_DIMENSION_NAMES: Tuple[str, ...] = (
    "record_type", "role", "model", "compact_subtype", "is_compact_boundary",
    "parent_uuid", "ts", "message_uuid", "content_shape",
    "content_block_types", "usage_shape", "stop_reason", "body_toplevel_type",
)



_NOT_EVALUATED: List[Tuple[str, str]] = []


def record_not_evaluated(guarantee: str, reason: str) -> str:
    message = f"COULD-NOT-EVALUATE: {guarantee} - {reason}"
    _NOT_EVALUATED.append((guarantee, reason))
    return message


def not_evaluated_entries() -> List[Tuple[str, str]]:
    return list(_NOT_EVALUATED)



def corpus_path() -> Optional[str]:
    override = os.environ.get(CORPUS_DB_ENV_VAR)
    if override:
        return override if Path(override).is_file() else None
    return DEFAULT_CORPUS_DB if Path(DEFAULT_CORPUS_DB).is_file() else None


def open_corpus_readonly(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60.0)
    conn.execute("PRAGMA query_only=ON")
    got = conn.execute("PRAGMA query_only").fetchone()[0]
    if got != 1:
        conn.close()
        raise RuntimeError(
            f"REFUSING to read {path}: PRAGMA query_only read back as {got!r}, "
            "not 1, so this connection is not provably read-only"
        )
    return conn


def load_manifest() -> Dict[str, Any]:
    with MANIFEST_PATH.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    found = manifest.get("schema_version")
    if found != SUPPORTED_MANIFEST_SCHEMA_VERSION:
        raise RuntimeError(
            f"manifest schema_version is {found!r}, but this module reads "
            f"only v{SUPPORTED_MANIFEST_SCHEMA_VERSION}. Re-read "
            "signature_definition before changing this number."
        )
    return manifest



def _classify_json(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def agent_id_form(agent_id: Optional[str]) -> str:
    if agent_id is None:
        return NULL_TOKEN
    for prefix in AGENT_ID_PREFIXES:
        if agent_id.startswith(prefix):
            return prefix
    return "other"


def key_order_digest(key_order_json: Optional[str]) -> str:
    text = KEY_ORDER_NULL_SENTINEL if key_order_json is None else key_order_json
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return digest[:KEY_ORDER_DIGEST_HEX_CHARS]


def _key_order_len(key_order_json: Optional[str]) -> Optional[int]:
    if key_order_json is None:
        return None
    try:
        parsed = json.loads(key_order_json)
    except json.JSONDecodeError:
        return None
    return len(parsed) if isinstance(parsed, list) else None


def _envelope_keys(envelope_json: Optional[str]) -> Any:
    if envelope_json is None:
        return NULL_TOKEN
    try:
        parsed = json.loads(envelope_json)
    except json.JSONDecodeError:
        return [UNPARSEABLE_TOKEN]
    if not isinstance(parsed, dict):
        return [UNPARSEABLE_TOKEN]
    return sorted(parsed.keys())


def body_dimensions(
    body: Any, record_type: Optional[str], role: Optional[str],
    model: Optional[str], compact_subtype: Optional[str],
    is_compact_boundary: int, parent_uuid: Optional[str],
    ts: Optional[str], message_uuid: Optional[str],
) -> Dict[str, Any]:
    inner = body.get("message") if isinstance(body, dict) else None
    inner = inner if isinstance(inner, dict) else None
    if inner is None:
        content_shape = NO_MESSAGE_TOKEN
        blocks: List[str] = []
        usage_shape = NO_MESSAGE_TOKEN
        stop_reason = NO_MESSAGE_TOKEN
    else:
        content_shape = (
            ABSENT_TOKEN if "content" not in inner
            else _classify_json(inner["content"])
        )
        blocks = []
        if content_shape == "array":
            seen = set()
            for block in inner["content"]:
                if isinstance(block, dict):
                    kind = block.get("type")
                    seen.add(
                        kind if isinstance(kind, str) else NON_STRING_TYPE_TOKEN
                    )
                else:
                    seen.add(f"<non-object block:{_classify_json(block)}>")
            blocks = sorted(seen)
        usage_shape = (
            ABSENT_TOKEN if "usage" not in inner
            else _classify_json(inner["usage"])
        )
        if "stop_reason" not in inner:
            stop_reason = ABSENT_TOKEN
        elif inner["stop_reason"] is None:
            stop_reason = "null"
        elif isinstance(inner["stop_reason"], str):
            stop_reason = inner["stop_reason"]
        else:
            stop_reason = NON_STRING_TOKEN
    return {
        "record_type": record_type, "role": role, "model": model,
        "compact_subtype": compact_subtype,
        "is_compact_boundary": int(is_compact_boundary),
        "parent_uuid": "set" if parent_uuid is not None else "null",
        "ts": "set" if ts is not None else "null",
        "message_uuid": "set" if message_uuid is not None else "null",
        "content_shape": content_shape, "content_block_types": blocks,
        "usage_shape": usage_shape, "stop_reason": stop_reason,
        "body_toplevel_type": (
            "dict" if isinstance(body, dict) else _classify_json(body)
        ),
    }


def no_body_dimensions() -> Dict[str, Any]:
    dims: Dict[str, Any] = {name: None for name in BODY_DIMENSION_NAMES}
    dims["body_toplevel_type"] = NO_BODY_TOKEN
    return dims


def signature_id(dimensions: Dict[str, Any]) -> str:
    canonical = json.dumps(dimensions, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:SIGNATURE_ID_HEX_CHARS]
