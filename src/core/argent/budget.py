
from __future__ import annotations

import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional
from urllib.parse import quote

from src.core.argent import store

OK, WARN, HOLD = "ok", "warn", "hold"
_RANK = {OK: 0, WARN: 1, HOLD: 2}
WARN_SHARE = 0.8


@dataclass(frozen=True)
class Standing:

    state: str
    spent_micros: Optional[int]
    cap_micros: Optional[int]
    owner_name: str
    resets_at: Optional[str]
    governing_item_id: str = ""
    governing_item_title: str = ""

    @property
    def known(self) -> bool:
        return self.state in ("ok", "warn", "paused")


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_standing(body: Mapping[str, Any]) -> Standing:
    state = body.get("state")
    nested = body.get("governing_item") if isinstance(body.get("governing_item"), dict) else body.get("governing")
    nested = nested if isinstance(nested, dict) else {}
    flat = body.get("governing_item") if isinstance(body.get("governing_item"), str) else None
    return Standing(state if state in ("ok", "warn", "paused") else "unknown", _int(body.get("spent_micros")), _int(body.get("cap_micros")),
                    str(body.get("owner_name") or ""), str(body["resets_at"]) if body.get("resets_at") else None,
                    str(body.get("governing_work_item_id") or body.get("governing_item_id") or nested.get("id") or flat or ""),
                    str(body.get("governing_title") or body.get("governing_item_title") or nested.get("title") or ""))


@dataclass(frozen=True)
class Decision:

    held: Optional[bool]
    level: Optional[str]


def decide(standing: Standing, local_extra_micros: Optional[int]) -> Decision:
    if not standing.known:
        return Decision(None, None)
    cap, spent = standing.cap_micros, standing.spent_micros
    if standing.state == "paused":
        return Decision(True, HOLD)
    if cap and spent is not None and local_extra_micros is not None and spent + local_extra_micros >= cap:
        return Decision(True, HOLD)
    if local_extra_micros is None:
        return Decision(None, None)
    over_share = bool(cap and spent is not None and (spent + local_extra_micros) >= cap * WARN_SHARE)
    return Decision(False, WARN if standing.state == "warn" or over_share else OK)


NOC_BUDGET_URL_TEMPLATE: Optional[str] = "{server}/work/items?sel={item}"


def noc_budget_url(server_url: str, item_id: str) -> Optional[str]:
    if not NOC_BUDGET_URL_TEMPLATE or not server_url or not item_id:
        return None
    return NOC_BUDGET_URL_TEMPLATE.format(server=server_url.rstrip("/"), item=quote(item_id, safe=""))


def viewer_is_owner(owner_name: str, viewer_name: str) -> Optional[bool]:
    owner, viewer = owner_name.strip().casefold(), viewer_name.strip().casefold()
    return owner == viewer if owner and viewer else None


def near_cap(standing: Standing) -> bool:
    return bool(standing.cap_micros and standing.spent_micros is not None and standing.spent_micros >= standing.cap_micros * WARN_SHARE)


def _conn(state_dir: Optional[Path]) -> Any:
    return store.open_db(state_dir)


def last_level(tenant: str, item_id: str, *, state_dir: Optional[Path] = None) -> str:
    with closing(_conn(state_dir)) as conn:
        row = conn.execute("SELECT level FROM budget_level WHERE tenant_id = ? AND item_id = ?", (tenant, item_id)).fetchone()
    return str(row[0]) if row and row[0] in _RANK else OK


def move_level(tenant: str, item_id: str, level: str, *, state_dir: Optional[Path] = None) -> str:
    before = last_level(tenant, item_id, state_dir=state_dir)
    if before == level:
        return "same"
    with closing(_conn(state_dir)) as conn:
        conn.execute("INSERT INTO budget_level (tenant_id, item_id, level, updated_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(tenant_id, item_id) DO UPDATE SET level = excluded.level, updated_at = excluded.updated_at", (tenant, item_id, level, time.time()))
        conn.commit()
    return "rose" if _RANK[level] > _RANK[before] else "fell"


def price_micros(table: Mapping[str, Any], model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int, cache_write_tokens: int) -> Optional[int]:
    row = table.get(model) if isinstance(table, Mapping) else None
    if not isinstance(row, Mapping):
        return None
    total = 0
    for tokens, column in ((input_tokens, "input_micros"), (output_tokens, "output_micros"), (cache_read_tokens, "cache_read_micros"), (cache_write_tokens, "cache_write_micros")):
        if not tokens:
            continue
        rate = _int(row.get(column))
        if rate is None:
            return None
        total += tokens * rate
    return -(-total // 1_000_000)


def money(micros: Optional[int]) -> str:
    if micros is None:
        return "-"
    dollars = micros / 1_000_000
    text = f"{dollars:.4f}"
    if micros == 0 or float(text) >= 1:
        return f"${dollars:,.2f}"
    if float(text) == 0:
        return "$0.0001"
    whole, frac = text.split(".")
    return f"${whole}.{frac.rstrip('0').ljust(2, '0')}"
