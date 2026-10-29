
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.widgets.verdicts import FAIL, PASS, UNSUPPORTED

FIT_TABLE_SCHEMA = 1
FIT_TABLE_FILE = "fit-table.json"
HOST_ORDER = ("home", "terminal", "drawer", "glance", "popout")


def _host_rank(host: str) -> int:
    return HOST_ORDER.index(host) if host in HOST_ORDER else len(HOST_ORDER)


def build_table(gates: Sequence[Mapping[str, Any]], source_revision: Mapping[str, Any] | None = None) -> dict[str, Any]:
    columns: dict[str, set[str]] = {}
    for gate in gates:
        for cell in gate.get("cells", []):
            columns.setdefault(cell["host"], set()).add(cell["size"])
    hosts = {host: sorted(columns[host]) for host in sorted(columns, key=_host_rank)}
    counts = {PASS: 0, FAIL: 0, UNSUPPORTED: 0}
    widgets = []
    for gate in gates:
        mine = {f"{c['host']}/{c['size']}": c for c in gate.get("cells", [])}
        cells: dict[str, Any] = {}
        for host, sizes in hosts.items():
            for size in sizes:
                cell = mine.get(f"{host}/{size}")
                if cell is None:
                    cell = {"verdict": UNSUPPORTED, "red": False, "draws": 0, "reasons": []}
                cells[f"{host}/{size}"] = {"verdict": cell["verdict"], "red": cell["red"], "draws": cell["draws"], "reasons": cell["reasons"]}
                counts[cell["verdict"]] += 1
        widgets.append({"widget": gate["widget"], "ok": bool(gate.get("ok")), "determined": gate.get("determined") is True,
                        "failures": len(gate.get("failures", [])), "cells": cells})
    return {"schema": FIT_TABLE_SCHEMA, "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "source_revision": dict(source_revision or {}), "hosts": hosts, "counts": counts, "widgets": widgets}


def read_gates(out: Path) -> list[dict[str, Any]]:
    gates = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out.glob("*.gate.json"))]
    return sorted(gates, key=lambda g: g["widget"])


def write_table(out: Path, gates: Sequence[Mapping[str, Any]], source_revision: Mapping[str, Any] | None = None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    path = out / FIT_TABLE_FILE
    path.write_text(json.dumps(build_table(gates, source_revision), indent=1) + "\n", encoding="utf-8")
    return path
