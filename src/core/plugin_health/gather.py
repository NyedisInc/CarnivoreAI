
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.db import connect, db_path_for
from src.core.plugin_health import model
from src.core.plugin_health.claude_plugins import measured_digest
from src.core.plugin_health.classify import SidecarFacts, classify_claude_plugin, classify_listing_state, classify_sidecar
from src.core.plugin_health.model import HealthReport, HealthRow, RemovedInstall, Verdict
from src.core.plugin_health.presence import PRESENT, folder_presence
from src.core import plugin_layout
from src.core.plugin_health.sizes import dir_bytes, orphan_folders
from src.core.skills import kinds
from src.core.skills.ledger import InstallLedger
from src.core.skills.ledger_types import InstalledItem
from src.cplugs.host import gate, identity, install_folder, registry_store, risk, runtime, sideload, sidecar_registry
from src.cplugs.sdk.api_contract import read_api_version
from src.cplugs.host import state as owner_state

logger = structlog.get_logger()

_SHIPPED_ROOT = Path(runtime.__file__).resolve().parents[1]
_BUILTIN_SOURCE = "builtin"
LedgerRows = List[Tuple[InstalledItem, Tuple[str, ...]]]


def read_ledger(state_dir: Path) -> LedgerRows:
    path = db_path_for(state_dir)
    if not path.exists():
        return []
    conn = connect(path, create=False)
    try:
        ledger = InstallLedger(conn)
        return [(row, tuple(t.path for t in ledger.targets(row.install_id))) for row in ledger.list()]
    finally:
        conn.close()


def _verdict_row(verdict: Verdict, *, id: str, kind: str, source: str, version: Optional[str], data_bytes: int,
                 api_version: Optional[int] = None) -> HealthRow:
    return HealthRow(id=id, kind=kind, source=source, word=verdict.word, reason=verdict.reason, button=verdict.button,
                     version=version, data_bytes=data_bytes, api_version=api_version)


def _feature_rows(host: Any) -> List[HealthRow]:
    from src.cplugs.host.routes import cplug_row  # noqa: PLC0415

    rows: List[HealthRow] = []
    for d in runtime.definitions():
        if runtime.hidden(d):
            continue
        listing = cplug_row(host, d)
        rows.append(_verdict_row(classify_listing_state(listing["state"], listing.get("detail")), id=d.id, kind=model.KIND_FEATURE,
                                 source=model.SOURCE_BUILT_IN, version=d.manifest.version, data_bytes=int(listing.get("storage_bytes") or 0),
                                 api_version=read_api_version(_SHIPPED_ROOT / d.id)))
    return rows


def sidecar_facts(host: Any, live: Optional[Any], item: InstalledItem, records: Dict[str, identity.InstallRecord]) -> SidecarFacts:
    state_dir = Path(host.state_dir)
    name = item.item_id.partition("/")[2]
    local = sideload.is_local(item.item_id)
    registry = sidecar_registry.current()
    d = registry.find(name) if registry is not None else None
    presence = _worst_presence(state_dir, item.item_id, local)
    base = dict(folder=presence, in_registry=d is not None, record_ok=name in records and records[name].catalog_id == item.item_id,
                local=local, sideload_on=sideload.is_on(state_dir, sideload.wall) if local else True)
    if d is None:
        return SidecarFacts(**base)
    st = owner_state.get(state_dir, d.manifest)
    admit, process, runtime_up, safe_flag = None, "unknown", live is not None, False
    if live is not None:
        admit = _dry_admit(host, live, d)
        process = live.supervisor.state(d.id)
        why = live.safe_mode()
        safe_flag = bool(why.get("env") or why.get("owner"))
    return SidecarFacts(**base, enabled=st.enabled, consented=bool(st.digest),
                        owed=risk.consent_owed(d.manifest.tier, d.manifest.code_digest, st.digest),
                        grants_missing=any(p not in st.grants for p in d.manifest.permissions), admit=admit, runtime_up=runtime_up,
                        safe_env_or_owner=safe_flag, process=process, blocked_by=tuple(gate.blocked_by(d.id, state_dir)))


def _worst_presence(state_dir: Path, item_id: str, local: bool) -> str:
    found = folder_presence(install_folder.deciding_folder(state_dir, item_id))
    if found == PRESENT and local:
        found = folder_presence(sideload.code_root_of(state_dir, item_id.partition("/")[2]))
    return found


def _dry_admit(host: Any, live: Any, d: Any) -> Optional[str]:
    try:
        return live.supervisor.admit(host.sidecar_spec(d))
    except (OSError, ValueError, KeyError) as exc:
        logger.warning("plugin_health_admit_failed", plugin=d.id, error_type=type(exc).__name__)
        return "unbuildable"


def _sidecar_rows(host: Any, live: Optional[Any], ledger: LedgerRows, records: Dict[str, identity.InstallRecord]) -> List[HealthRow]:
    rows: List[HealthRow] = []
    state_dir = Path(host.state_dir)
    for item, _targets in ledger:
        if item.kind != kinds.KIND_CPLUG or item.source_index_url == _BUILTIN_SOURCE or "/" not in item.item_id:
            continue
        name = item.item_id.partition("/")[2]
        facts = sidecar_facts(host, live, item, records)
        record = records.get(name)
        size = dir_bytes(identity.data_dir(state_dir, record.uuid)) if record is not None else 0
        rows.append(_verdict_row(classify_sidecar(facts), id=item.item_id, kind=model.KIND_PLUGIN,
                                 source=model.SOURCE_FOLDER if facts.local else model.SOURCE_CATALOG, version=item.version, data_bytes=size,
                                 api_version=read_api_version(plugin_layout.code_root(state_dir, name))))
    return rows


def _deployed_verdict(folder: Path, recorded: str) -> Verdict:
    presence = folder_presence(folder)
    return classify_claude_plugin(presence, recorded, measured_digest(folder) if presence == PRESENT else None)


def _claude_plugin_rows(ledger: LedgerRows) -> List[HealthRow]:
    rows: List[HealthRow] = []
    for item, targets in ledger:
        if item.kind != kinds.KIND_PLUGIN:
            continue
        recorded = item.consented_digest or item.digest or ""
        verdicts = [_deployed_verdict(Path(t), recorded) for t in targets] or [classify_claude_plugin(PRESENT, recorded, recorded)]
        verdict = next((v for v in verdicts if v.word != model.WORD_ON), verdicts[0])
        rows.append(_verdict_row(verdict, id=item.item_id, kind=model.KIND_CLAUDE_CODE_PLUGIN,
                                 source=model.SOURCE_FOLDER if item.source_index_url == "sideload" else model.SOURCE_CATALOG,
                                 version=item.version, data_bytes=0))
    return rows


def _first_party_keys() -> Tuple[set, set]:
    shipped = {d.id for d in runtime.definitions()}
    legacy = {old for d in runtime.definitions() for old in d.manifest.legacy_ids}
    return shipped, legacy


def build_report(host: Any, live: Optional[Any] = None) -> HealthReport:
    state_dir = Path(host.state_dir)
    report = HealthReport()
    report.rows.extend(_feature_rows(host))
    try:
        ledger = read_ledger(state_dir)
    except (sqlite3.Error, OSError) as exc:
        logger.warning("plugin_health_ledger_unreadable", error_type=type(exc).__name__)
        ledger = []
        report.problems.append("install_ledger_unreadable")
    try:
        records = {r.name: r for r in identity.installs(state_dir)}
    except identity.LedgerUnreadable:
        records = {}
        report.problems.append("installs_unreadable")
    report.rows.extend(_sidecar_rows(host, live, ledger, records))
    report.rows.extend(_claude_plugin_rows(ledger))
    if live is None:
        report.problems.append("runtime_unavailable")
    _fill_leftovers(report, state_dir, ledger, records)
    report.registry_generation, report.registry_source = registry_store.describe(state_dir)
    return report


def _removed(state_dir: Path, record: identity.InstallRecord) -> RemovedInstall:
    try:
        tomb = identity.removal_of(state_dir, record.name) or {}
    except identity.LedgerUnreadable:
        tomb = {}
    return RemovedInstall(record.name, record.catalog_id, dir_bytes(identity.data_dir(state_dir, record.uuid)), tomb.get("at"), tomb.get("version"))


def _fill_leftovers(report: HealthReport, state_dir: Path, ledger: LedgerRows, records: Dict[str, identity.InstallRecord]) -> None:
    shipped, legacy = _first_party_keys()
    held_names = {i.item_id.partition("/")[2] for i, _ in ledger if i.kind == kinds.KIND_CPLUG}
    for name, record in sorted(records.items()):
        if name not in held_names:
            report.removed.append(_removed(state_dir, record))
    owned = shipped | legacy | {r.uuid for r in records.values()}
    if "installs_unreadable" not in report.problems:
        for root in (plugin_layout.data_parent(state_dir), state_dir / owner_state.STATE_DIR_NAME):
            report.orphan_data.extend(orphan_folders(root, owned))
        report.stale_state.extend(i for i in owner_state.stored_ids(state_dir) if i not in shipped | legacy | set(records))
