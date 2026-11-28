
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.core.catalog import publish_facts, publish_prepare_kinds
from src.core.plugin_studio import store
from src.plugins.cli import checker, tester
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS
from src.plugins.sdk.manifest_v2 import JSON_FILE, TOML_FILE

REPO_ROOT = Path(__file__).resolve().parents[3]
_DIGEST_DOMAIN = b"carnivore-skill-digest-v1\n"
_STUDIO_PREVIEW_HANDLE = "studio-preview"
_GATE_CATEGORIES = {
    1: "structure",
    2: "schema",
    3: "policy",
    4: "identity",
    5: "integrity",
    6: "security",
    7: "secrets",
    8: "license",
    9: "dependencies",
    12: "grade",
}


def _digest_staged_directory(root: Path) -> str:
    entries: List[Tuple[str, str, str]] = []
    root_str = str(root)
    for dirpath, _dirnames, filenames in os.walk(root_str, followlinks=False):
        for filename in filenames:
            full = Path(dirpath) / filename
            info = os.lstat(full)
            if not stat.S_ISREG(info.st_mode):
                continue
            relpath = os.path.relpath(str(full), root_str).replace(os.sep, "/")
            h = hashlib.sha256()
            with full.open("rb") as fh:
                while True:
                    chunk = fh.read(64 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
            mode = "100755" if (info.st_mode & stat.S_IXUSR) else "100644"
            entries.append((relpath, mode, h.hexdigest()))
    entries.sort(key=lambda item: item[0].encode("utf-8"))
    rendered = b"".join(
        mode.encode("ascii") + b"\0" + rel.encode("utf-8") + b"\0" + sha.encode("ascii") + b"\n"
        for rel, mode, sha in entries
    )
    return hashlib.sha256(_DIGEST_DOMAIN + rendered).hexdigest()


def _stage_clean_folder(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for dirpath, dirnames, filenames in os.walk(src, followlinks=False):
        rel_dir = Path(dirpath).relative_to(src)
        dirnames[:] = sorted(d for d in dirnames if d not in DEV_SKIP_DIRS)
        for dname in dirnames:
            (dst / rel_dir / dname).mkdir(parents=True, exist_ok=True)
        for fname in sorted(filenames):
            if fname == ".DS_Store" or fname.startswith("._") or fname.endswith((".pyc", ".pyo")):
                continue
            full = Path(dirpath) / fname
            if full.is_symlink() or not full.is_file():
                continue
            target = dst / rel_dir / fname
            shutil.copy2(full, target)

    toml_path = dst / TOML_FILE
    json_path = dst / JSON_FILE
    try:
        if toml_path.is_file():
            raw = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and (raw.get("tier") == "local" or raw.get("default_enabled") is True):
                raw["tier"] = "catalog"
                raw["default_enabled"] = False
                toml_path.write_bytes(publish_prepare_kinds._toml_text(raw))
        elif json_path.is_file():
            raw = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and (raw.get("tier") == "local" or raw.get("default_enabled") is True):
                raw["tier"] = "catalog"
                raw["default_enabled"] = False
                json_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ValueError, publish_prepare_kinds.TomlEncodeError):
        pass


def _materialize_catalog_stub(catalog_dir: Path) -> bool:
    builder_src = REPO_ROOT / "hosted" / "catalog_index" / "tools" / "index_builder"
    if not builder_src.is_dir():
        return False
    (catalog_dir / "releases").mkdir(parents=True, exist_ok=True)
    (catalog_dir / "tools").mkdir(parents=True, exist_ok=True)
    target = catalog_dir / "tools" / "index_builder"
    try:
        target.symlink_to(builder_src, target_is_directory=True)
    except OSError:
        shutil.copytree(builder_src, target)
    return True


def _run_warez_gates_subprocess(
    folder: Path,
    *,
    plugin_id: str,
    version: str,
    handle: str,
    timeout_s: float,
) -> Dict[str, Any]:
    if not (REPO_ROOT / "scripts" / "warez_gates").is_dir():
        return {"available": False, "gates": [], "digest": ""}

    with tempfile.TemporaryDirectory(prefix="studio_warez_") as tmp_str:
        tmp = Path(tmp_str)
        staged = tmp / "staged"
        catalog_dir = tmp / "catalog"
        if not _materialize_catalog_stub(catalog_dir):
            return {"available": False, "gates": [], "digest": ""}
        _stage_clean_folder(folder, staged)
        digest = _digest_staged_directory(staged)
        facts = {
            "submission_id": "00000000000000000000000000000000",
            "kind": "cplug",
            "handle": handle or _STUDIO_PREVIEW_HANDLE,
            "name": plugin_id,
            "version": version,
            "folder_digest": digest,
        }
        facts_path = tmp / "facts.json"
        out_path = tmp / "static_out.json"
        facts_path.write_text(json.dumps(facts), encoding="utf-8")

        import subprocess  # noqa: PLC0415

        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.warez_gates",
                    "static",
                    "--folder",
                    str(staged),
                    "--catalog",
                    str(catalog_dir),
                    "--facts-file",
                    str(facts_path),
                    "--out",
                    str(out_path),
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "available": True,
                "error": "warez_gates_static_timeout",
                "gates": [],
                "digest": digest,
            }
        if not out_path.is_file():
            return {
                "available": True,
                "error": f"warez_gates_static_exit_{proc.returncode}: {(proc.stderr or proc.stdout).strip()[:240]}",
                "gates": [],
                "digest": digest,
            }
        doc = json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "available": True,
            "gates": list(doc.get("gates") or []),
            "extra": doc.get("extra") or {},
            "digest": digest,
        }


def _map_gate_verdict(verdict: str) -> str:
    if verdict == "pass":
        return "pass"
    if verdict == "advisory":
        return "advisory"
    if verdict == "undetermined":
        return "undetermined"
    return "fail"


def _item(
    item_id: str,
    label: str,
    category: str,
    status: str,
    code: str,
    detail: str,
    findings: Optional[Iterable[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "id": item_id,
        "label": label,
        "category": category,
        "status": status,
        "code": code,
        "detail": detail,
        "findings": list(findings or []),
    }


def _build_readiness_blocking(
    folder: Path,
    *,
    handle: str = "",
    run_tests: bool = False,
    include_warez_gates: bool = True,
    timeout_s: float = 45.0,
) -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    check_rep = checker.check_folder(folder)
    manifest = check_rep.manifest_v2
    plugin_id = manifest.id if manifest is not None else folder.name
    version = manifest.version if manifest is not None else (publish_facts.declared_version(publish_prepare_kinds.KIND_CPLUG, str(folder)) or "0.1.0")

    if check_rep.ok:
        items.append(_item("check_manifest", "Manifest & Tree Validation", "schema", "pass", "ok", "Manifest v2, ID, files, and local secret checks passed."))
    else:
        items.append(_item(
            "check_manifest",
            "Manifest & Tree Validation",
            "schema",
            "fail",
            "check_failed",
            "; ".join(check_rep.errors[:5]),
            [{"code": "check_error", "detail": err} for err in check_rep.errors],
        ))
    if check_rep.warnings:
        items.append(_item(
            "check_warnings",
            "Manifest Warnings",
            "security",
            "advisory",
            "check_warnings",
            "; ".join(check_rep.warnings[:3]),
            [{"code": "warning", "detail": w} for w in check_rep.warnings],
        ))

    eff_handle = (handle or "").strip() or _STUDIO_PREVIEW_HANDLE
    prepared = publish_prepare_kinds.prepare_kind(publish_prepare_kinds.KIND_CPLUG, str(folder), version, eff_handle)
    if prepared.refusals:
        items.append(_item(
            "prepare_kind",
            "Package Caps & Upload Rules",
            "structure",
            "fail",
            prepared.refusals[0].code,
            "; ".join(r.detail for r in prepared.refusals[:4]),
            [{"code": r.code, "detail": r.detail, "path": r.path} for r in prepared.refusals],
        ))
    else:
        items.append(_item(
            "prepare_kind",
            "Package Caps & Upload Rules",
            "structure",
            "pass",
            "ok",
            f"{len(prepared.members)} files ({prepared.total_bytes} bytes) ready for packaging.",
        ))

    if not (handle or "").strip():
        items.append(_item(
            "publisher_handle",
            "Warez Publisher Handle",
            "identity",
            "advisory",
            "handle_unclaimed",
            "Sign in and claim a Warez publisher handle before submitting to Warez.",
        ))

    if run_tests:
        test_rep = tester.test_folder(folder)
        if test_rep.ok:
            items.append(_item(
                "sandbox_test",
                "Unit Tests & Sandbox Smoke",
                "runtime",
                "pass",
                "ok",
                "Unit tests and OS sandbox smoke probe passed.",
            ))
        else:
            is_sandbox_unavail = any("SandboxUnavailable" in e for e in test_rep.errors)
            items.append(_item(
                "sandbox_test",
                "Unit Tests & Sandbox Smoke",
                "runtime",
                "unavailable" if is_sandbox_unavail else "fail",
                "sandbox_unavailable" if is_sandbox_unavail else "test_failed",
                "; ".join(test_rep.errors[:4]),
                [{"code": "test_error", "detail": e} for e in test_rep.errors],
            ))

    digest = prepared.digest
    if include_warez_gates:
        gate_run = _run_warez_gates_subprocess(
            folder,
            plugin_id=plugin_id,
            version=version,
            handle=eff_handle,
            timeout_s=timeout_s,
        )
        if gate_run.get("digest"):
            digest = str(gate_run["digest"])
        if not gate_run.get("available"):
            items.append(_item(
                "warez_gates",
                "Warez Static Gates",
                "security",
                "unavailable",
                "warez_gates_unavailable",
                "Warez static gate runner is not present in this packaged build.",
            ))
        elif gate_run.get("error") == "warez_gates_static_timeout":
            items.append(_item(
                "warez_gates",
                "Warez Static Gates",
                "security",
                "fail",
                "warez_gates_static_timeout",
                f"Warez static gate runner timed out after {timeout_s}s.",
            ))
        elif gate_run.get("error"):
            items.append(_item(
                "warez_gates",
                "Warez Static Gates",
                "security",
                "undetermined",
                "warez_gates_error",
                str(gate_run["error"]),
            ))
        else:
            for g in gate_run.get("gates", []):
                n = int(g.get("n") or 0)
                gid = str(g.get("id") or f"gate_{n}")
                verdict = str(g.get("verdict") or "undetermined")
                code = str(g.get("code") or "")
                findings = list(g.get("findings") or [])
                status = _map_gate_verdict(verdict)
                detail = code or ("passed" if status == "pass" else verdict)
                if findings and status in ("fail", "advisory"):
                    detail = "; ".join(
                        f"{f.get('code') or 'finding'}" + (f" ({f.get('path')})" if f.get("path") else "")
                        for f in findings[:4]
                    )
                items.append(_item(
                    f"gate_{n:02d}_{gid}",
                    f"Gate {n}: {gid.replace('_', ' ').title()}",
                    _GATE_CATEGORIES.get(n, "security"),
                    status,
                    code or ("ok" if status == "pass" else verdict),
                    detail,
                    findings,
                ))

    summary = {"pass": 0, "fail": 0, "advisory": 0, "undetermined": 0, "unavailable": 0}
    for it in items:
        st = it["status"]
        summary[st] = summary.get(st, 0) + 1
    ready = summary["fail"] == 0 and summary["undetermined"] == 0
    return {
        "ok": ready,
        "ready": ready,
        "items": items,
        "checked_at": store.utc_now_iso(),
        "digest": digest,
        "summary": summary,
    }


async def check_readiness(
    folder: Path,
    *,
    handle: str = "",
    run_tests: bool = False,
    include_warez_gates: bool = True,
    timeout_s: float = 45.0,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _build_readiness_blocking,
        folder,
        handle=handle,
        run_tests=run_tests,
        include_warez_gates=include_warez_gates,
        timeout_s=timeout_s,
    )
