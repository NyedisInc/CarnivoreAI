
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.cplugs.save.vault.points import SessionIndex


def test_the_scan_reads_one_manifest_per_unit() -> None:
    reads: list[str] = []
    newest = {"conv-a": SimpleNamespace(session_uuid="s1"), "conv-b": SimpleNamespace(session_uuid="s1"), "conv-c": SimpleNamespace(session_uuid=None)}

    def read_newest(unit: str):
        reads.append(unit)
        return newest[unit]

    def points(unit: str):
        raise AssertionError("every point of a unit must not be parsed")

    manifests = SimpleNamespace(units=lambda: sorted(newest), newest=read_newest, points=points)
    vault = SimpleNamespace(root=Path("/v"), manifests=manifests)
    index = SessionIndex()
    assert index.conversations(vault, "s1") == ["conv-a", "conv-b"]
    assert index.conversations(vault, "none") == [] and sorted(reads) == ["conv-a", "conv-b", "conv-c"]
