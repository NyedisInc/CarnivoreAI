from pathlib import Path
from types import SimpleNamespace

from src.core import theme_catalog_consent as tcc
from src.core.ui_preferences_store import COMMITTED, REJECTED_INVALID, STALE_REVISION

FIELD = tcc.CONSENT_FIELD


class RacingStore:

    def __init__(self, statuses: list[str]) -> None:
        self.map = {"neon": {"decision": "always", "digest": "a" * 64}}
        self.revision = 1
        self.statuses = statuses
        self.updates: list[tuple[dict, int]] = []

    def read(self) -> dict:
        return {"revision": self.revision, "values": {FIELD: dict(self.map)}}

    def update(self, changes: dict, expected_revision=None) -> SimpleNamespace:
        self.updates.append((changes, expected_revision))
        status = self.statuses.pop(0)
        if status == STALE_REVISION:
            self.map["other"] = {"decision": "never"}
            self.revision += 1
        elif status == COMMITTED:
            self.map = changes[FIELD] or {}
        return SimpleNamespace(status=status)


def _drop(store: RacingStore, tmp_path: Path) -> bool:
    return tcc.drop_stale_effects_grant(store, "neon", tmp_path)


def test_stale_revision_retries_once_and_keeps_the_concurrent_never(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tcc, "effects_digest_of", lambda d: "b" * 64)
    store = RacingStore([STALE_REVISION, COMMITTED])
    assert _drop(store, tmp_path) is True
    assert [rev for _, rev in store.updates] == [1, 2]
    assert store.map == {"other": {"decision": "never"}}


def test_rejected_write_does_not_report_a_dropped_grant(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tcc, "effects_digest_of", lambda d: "b" * 64)
    store = RacingStore([REJECTED_INVALID])
    assert _drop(store, tmp_path) is False
