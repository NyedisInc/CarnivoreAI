
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.plugins.cli import checker
from src.plugins.host import sidecar_registry, sidecar_spec, ui_doc
from src.plugins.host.plugin_manifest import SidecarManifestError, load_sidecar_manifest
from src.plugins.host.sideload_copy import DEV_SKIP_DIRS, copy_tree
from src.plugins.runtime import frames, sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.process import PluginProcess, ProcessEnded
from src.plugins.runtime.socket_server import PluginSocketManager

REPO_ROOT = Path(__file__).resolve().parents[3]
TEST_TIMEOUT_S = 120


class TesterToolError(RuntimeError):
    pass


@dataclass
class TestReport:

    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    unit_output: str = ""
    smoke_summary: Dict[str, Any] = field(default_factory=dict)


def _clean_env() -> Dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "COV_CORE_", "COVERAGE_"))}


def _run_python_tests(source: Path, runtime_dir: Path) -> Optional[TupleResult]:
    tests_dir = source / "tests"
    if not tests_dir.is_dir():
        return None
    py_tests = [p for p in tests_dir.rglob("*.py") if p.name.startswith("test_") or p.name.endswith("_test.py")]
    if not py_tests:
        return None
    env = {
        **_clean_env(),
        "PYTHONPATH": os.pathsep.join([str(runtime_dir), str(source), str(REPO_ROOT)]),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=str(source),
        env=env,
        capture_output=True,
        text=True,
        timeout=TEST_TIMEOUT_S,
        check=False,
    )
    out = (done.stdout.strip() + ("\n" + done.stderr.strip() if done.returncode != 0 and done.stderr.strip() else "")).strip()
    return TupleResult(done.returncode, out)


def _run_ts_tests(source: Path, runtime_dir: Path) -> Optional[TupleResult]:
    tests_dir = source / "tests"
    if not tests_dir.is_dir():
        return None
    ts_tests = sorted(
        p
        for p in tests_dir.rglob("*")
        if p.is_file() and p.name.endswith((".test.ts", ".test.mts", ".test.js", ".test.mjs"))
    )
    if not ts_tests:
        return None

    sdk_ts_dir = runtime_dir / "node_modules" / "@carnivore" / "plugin-sdk"
    node_modules_dir = runtime_dir / "node_modules"
    env = {
        **_clean_env(),
        "NODE_PATH": str(node_modules_dir),
        "CARNIVORE_SDK_TS_DIR": str(sdk_ts_dir),
    }

    uses_vitest = any('from "vitest"' in p.read_text(encoding="utf-8", errors="ignore") or "from 'vitest'" in p.read_text(encoding="utf-8", errors="ignore") for p in ts_tests)
    uses_bun = any('from "bun:test"' in p.read_text(encoding="utf-8", errors="ignore") or "from 'bun:test'" in p.read_text(encoding="utf-8", errors="ignore") for p in ts_tests)

    vitest_bin = REPO_ROOT / "web" / "node_modules" / ".bin" / "vitest"
    if uses_vitest and vitest_bin.is_file():
        cmd = [str(vitest_bin), "run"]
    elif uses_bun or (not uses_vitest and shutil.which("node") is None and shutil.which("bun") is not None):
        bun_exe = str(sandbox._find_bun())
        bun_ts = runtime_dir / "sdk_ts" / "bun_paths.json"
        extra = [f"--tsconfig-override={bun_ts}"] if bun_ts.is_file() else []
        cmd = [bun_exe, "test", *extra, *[str(p.relative_to(source)) for p in ts_tests]]
    else:
        node_exe = str(sandbox._find_node())
        preload = runtime_dir / "sdk_ts" / "node_preload.mjs"
        cmd = [
            node_exe,
            f"--import={preload}",
            "--experimental-strip-types",
            "--test",
            *[str(p.relative_to(source)) for p in ts_tests],
        ]

    done = subprocess.run(
        cmd,
        cwd=str(source),
        env=env,
        capture_output=True,
        text=True,
        timeout=TEST_TIMEOUT_S,
        check=False,
    )
    out = (done.stdout.strip() + ("\n" + done.stderr.strip() if done.returncode != 0 and done.stderr.strip() else "")).strip()
    return TupleResult(done.returncode, out)


@dataclass(frozen=True)
class TupleResult:
    returncode: int
    output: str


async def _run_v2_sandbox_smoke(source: Path, tmp: Path) -> Dict[str, Any]:
    code_dir = tmp / "code"
    data_dir = tmp / "data"
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    copy_tree(source, code_dir, skip_dirs=DEV_SKIP_DIRS)

    manifest = load_sidecar_manifest(code_dir, _manifest_id(source), allow_local=True)
    if manifest.tier0:
        if manifest.ui_meta and isinstance(manifest.ui_meta.get("widget"), dict):
            w = manifest.ui_meta["widget"]
            doc = w.get("document")
            if isinstance(w.get("ui_file"), str):
                doc = json.loads((code_dir / w["ui_file"]).read_text(encoding="utf-8"))
            if doc is not None:
                ui_doc.validate(doc, routes=manifest.routes, tools=[t.get("name") for t in manifest.tools if isinstance(t, dict)])
        return {"mode": "tier0", "ok": True}

    defn = sidecar_registry.SidecarDefinition(
        manifest=manifest,
        item_id=f"local/{manifest.id}",
        install_key=f"smoke-{manifest.id}",
        code_root=code_dir,
        folder=data_dir,
    )
    grants = frozenset(manifest.permissions)
    spec = sidecar_spec.build_spec(defn, grants, {}, consented=True, consent_owed=False)

    runtime_dir = sandbox.copy_runtime(tmp / "state", "smoke")
    rt = sandbox.resolve_runtime(spec.run_cmd, code_dir, allow_fork_for_bin=True)
    dispatcher = HostDispatcher(HostServices(activity=lambda _r: None), OwnerTokens(b"t" * 32))
    sockets = PluginSocketManager()
    sock_path = await sockets.ensure(tmp / "state", spec.ctx, dispatcher)
    layout = sandbox.Layout(
        interpreter=rt.interpreter,
        stdlib_root=rt.stdlib_root,
        runtime_dir=runtime_dir,
        code_dir=Path(os.path.realpath(code_dir)),
        data_dir=Path(os.path.realpath(data_dir)),
        runtime_kind=rt.kind,
        read_roots=rt.read_roots,
        exec_paths=rt.exec_paths,
        allow_fork=rt.allow_fork,
        socket_path=sock_path,
        plugin_id=manifest.id,
        run_mode=spec.run_mode,
        pythonpath_extra=rt.pythonpath_extra,
    )
    proc = PluginProcess(spec, layout, dispatcher, "1.0.0", lambda _why: asyncio.sleep(0))
    summary: Dict[str, Any] = {"mode": spec.run_mode, "runtime": rt.kind, "ui_checked": False, "tool_checked": None}
    try:
        await proc.start()
        if spec.run_mode == "rpc":
            await proc.request("ping", {}, timeout=5.0)
        try:
            ui_res = await proc.request("ui.render", {"surface": "widget", "params": {}}, timeout=5.0)
            if isinstance(ui_res, dict) and "document" in ui_res:
                ui_doc.validate(
                    ui_res["document"],
                    routes=manifest.routes,
                    tools=[t.get("name") for t in manifest.tools if isinstance(t, dict)],
                )
                summary["ui_checked"] = True
        except ProcessEnded as exc:
            if not exc.no_such_surface:
                raise
        for t in manifest.tools:
            if not isinstance(t, dict):
                continue
            schema = t.get("inputSchema") or {}
            if t.get("gate", "read") == "read" and not schema.get("required"):
                res = await proc.request("tools/call", {"name": t["name"], "arguments": {}, "caller": {"kind": "owner"}}, timeout=5.0)
                if not isinstance(res, dict) or "content" not in res:
                    raise TesterToolError(f"tool {t['name']} returned invalid tools/call payload")
                summary["tool_checked"] = t["name"]
                break
        await proc.stop("smoke", stop_timeout=0.5)
    finally:
        await sockets.stop_all()
        if not proc.ended:
            await proc.kill("smoke")
    return summary


def _manifest_id(source: Path) -> str:
    from src.plugins.sdk.manifest_v2 import load_raw_v2  # noqa: PLC0415

    raw, _ = load_raw_v2(source)
    return str(raw.get("id") or source.name)


def test_folder(folder: Path, *, unit_only: bool = False, smoke_only: bool = False) -> TestReport:
    report = checker.check_folder(folder)
    if not report.ok or report.manifest_v2 is None:
        return TestReport(
            ok=False,
            errors=list(report.errors) or ["carnivore.toml (or schema = 2 carnivore.json) is required"],
            warnings=list(report.warnings),
        )

    errors: List[str] = []
    outputs: List[str] = []
    smoke_summary: Dict[str, Any] = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        runtime_dir = sandbox.copy_runtime(tmp_path / "rt-state", "cli-test")
        if not smoke_only:
            py_res = _run_python_tests(folder, runtime_dir)
            if py_res is not None:
                if py_res.output:
                    outputs.append(py_res.output)
                if py_res.returncode != 0:
                    errors.append("python unit tests failed")
            ts_res = _run_ts_tests(folder, runtime_dir)
            if ts_res is not None:
                if ts_res.output:
                    outputs.append(ts_res.output)
                if ts_res.returncode != 0:
                    errors.append("typescript unit tests failed")
        if not unit_only:
            try:
                smoke_summary = asyncio.run(_run_v2_sandbox_smoke(folder, tmp_path / "smoke"))
            except (SidecarManifestError, sandbox.SandboxUnavailable, ProcessEnded, ui_doc.UiDocError, frames.FrameViolation, OSError, RuntimeError, asyncio.TimeoutError) as exc:
                errors.append(f"sandbox smoke failed ({type(exc).__name__}): {exc}")
    return TestReport(
        ok=not errors,
        errors=errors,
        warnings=list(report.warnings),
        unit_output="\n".join(outputs).strip(),
        smoke_summary=smoke_summary,
    )
