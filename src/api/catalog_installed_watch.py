
from __future__ import annotations

from typing import Any, Sequence

from src.core.skill_watch import sentinel
from src.core.skill_watch.store import default_watch_store
from src.core.skills.ledger_types import InstalledItem
from src.models.catalog_api import InstalledItemView
from src.models.skill_watch import DriftView


def annotate_watch(services: Any, rows: Sequence[InstalledItem],
                   views: Sequence[InstalledItemView], *, force: bool = False) -> None:
    store = default_watch_store()
    with services.catalog.ledger() as ledger:
        triples = [(r.install_id, r.digest, [t.path for t in ledger.targets(r.install_id)]) for r in rows]
        forks = ledger.forked_ids()
    verdicts = sentinel.refresh(store, triples, force=force)
    for row, view in zip(rows, views):
        drift = verdicts.get(row.install_id, sentinel.UNCHECKED)
        view.drift = DriftView(state=drift.state, changed_files=drift.changed_files,
                               checked_at=drift.checked_at)
        view.forked = row.install_id in forks
