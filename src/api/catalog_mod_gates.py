
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List, Tuple

from fastapi import HTTPException

from src.api.catalog_install_support import refuse_409
from src.api.mods_routes import ACCOUNTS_OK, account_settings_files
from src.core.mods import install_gates, registry
from src.core.server_status import collect_claude_cli

ModFacts = Tuple[Any, str, bool, List[str]]

_FINE = (registry.OK, registry.MISSING)


async def gate_staged_mod(version: Any, staged_path: Path) -> ModFacts:
    def work() -> ModFacts:
        cli = collect_claude_cli()
        report, sha, ack = install_gates.evaluate(cli.get("path"), cli.get("version"), staged_path, version.review)
        files, _status = account_settings_files()
        return report, sha, ack, [g.label for g in registry.groups_for(Path.home(), files)]

    try:
        return await asyncio.to_thread(work)
    except install_gates.ModGateRefusal as exc:
        raise refuse_409(exc.code, exc.detail)


def check_mod_consent(consent: Any, facts: ModFacts) -> None:
    try:
        install_gates.check_consent(consent, sha=facts[1], flagged_ack_needed=facts[2])
    except install_gates.ModGateRefusal as exc:
        raise refuse_409(exc.code, exc.detail)


def _targets(request: Any, install_id: str) -> List[str]:
    with request.app.state.services.catalog.ledger() as ledger:
        return [t.path for t in ledger.targets(install_id)]


def _results(paths: List[str], enable: bool) -> List[str]:
    files, status = account_settings_files()
    if status != ACCOUNTS_OK:
        return ["accounts_unreadable"]
    out: List[str] = []
    for path in paths:
        out += [r["status"] for r in registry.set_registered(path, enable, home=Path.home(), account_files=files)]
    return out


def register_installed(request: Any, install_id: str) -> str:
    statuses = _results(_targets(request, install_id), True)
    bad = [s for s in statuses if s not in _FINE]
    if not bad:
        return "ok"
    return "partial" if len(bad) < len(statuses) else "failed"


def unregister_planned(plan: Any) -> None:
    """Unregister the folders a replace is about to displace, so Claude never sees a half-moved mod (blocking).

    Raises: HTTPException 409 when a settings file could not be changed (nothing has moved yet).
    """
    refuse_unless_clean(_results([str(t.directory) for t in plan.targets if t.displaces is not None], False))


def unregister_before_uninstall(targets: Any) -> None:
    refuse_unless_clean(_results([t.path for t in targets], False))


def refuse_unless_clean(statuses: List[str]) -> None:
    bad = next((s for s in statuses if s not in _FINE), None)
    if bad is not None:
        raise HTTPException(status_code=409, detail={
            "code": bad, "detail": "a claude settings file could not be changed, so nothing was moved"})
