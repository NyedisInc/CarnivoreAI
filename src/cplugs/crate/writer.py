
from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.cplugs.crate import constants as K
from src.cplugs.crate import folders, manifest_out as M, policy as P, project_git, record, share as S, share_out as SO
from src.cplugs.crate.copying import CopyFailed, copy_crate
from src.cplugs.crate.entries_out import read_entries
from src.cplugs.crate.env import CrateEnv
from src.cplugs.crate.handle import ExportCancelled, JobHandle
from src.cplugs.crate.plan import ExportPlan, build_plan
from src.cplugs.crate.publish import NameTaken, age_readme, publish, sha_sidecar, write_new
from src.cplugs.crate.source_read import rehash
from src.cplugs.crate.write_files import FileWriter, write_lines
from src.cplugs.crate.write_rows import crate_store, write_rows
from src.cplugs.crate.forbidden import deny_inodes
from src.cplugs.sdk import blob_codec as bc
from src.cplugs.sdk import crate_format as cf
from src.cplugs.sdk import crate_sources as cs
from src.cplugs.sdk import exports as sx


class ExportRefused(Exception):

    def __init__(self, code: str, detail: Any) -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


class ExportFailed(Exception):

    def __init__(self, code: str, detail: Any) -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


@dataclass
class ExportResult:

    bundle_id: str
    file_name: str
    path: Path
    sha256: str
    size: int
    content_id: str
    variant: str
    encrypted: bool
    created_epoch: int
    findings: int
    verified_at: float
    recorded: bool = False
    second: Optional[Path] = None
    warnings: List[str] = field(default_factory=list)

    def as_json(self) -> Dict[str, Any]:
        return {"bundle_id": self.bundle_id, "file_name": self.file_name, "path": str(self.path), "sha256": self.sha256,
                "size": self.size, "content_id": self.content_id, "variant": self.variant, "encrypted": self.encrypted,
                "findings": self.findings, "verified_at": self.verified_at, "recorded": self.recorded,
                "second": str(self.second) if self.second else None, "warnings": list(self.warnings)}


class _Hashing:

    def __init__(self, raw: Any) -> None:
        self.raw, self.digest, self.size = raw, hashlib.sha256(), 0

    def write(self, b: Any) -> int:
        data = bytes(b)
        self.raw.write(data)
        self.digest.update(data)
        self.size += len(data)
        return len(data)

    def flush(self) -> None:
        self.raw.flush()


def mint_bundle_id(variant: str, scope: str, epoch: int) -> str:
    stamp = time.strftime(K.BUNDLE_STAMP_FMT, time.gmtime(epoch))
    prefix = K.PREFIX_SHARE if variant == P.SHARE else K.PREFIX_OWN
    return K.BUNDLE_ID_FMT.format(prefix=prefix, stamp=stamp, scope=scope, hex8=secrets.token_hex(4))


class _Run:

    def __init__(self, env: CrateEnv, plan: ExportPlan, job: JobHandle, codec: str, epoch: int, bundle_id: str) -> None:
        self.env, self.plan, self.job, self.codec, self.epoch, self.bundle_id = env, plan, job, codec, epoch, bundle_id
        self.encrypted = plan.request.encrypt
        self.share = plan.request.variant == P.SHARE
        self.stats = S.ShareStats()
        self.proof = bytearray()
        self.warnings: List[str] = list(plan.warnings)
        self.final = Path(str(plan.folder)) / cf.file_name(bundle_id, self.encrypted)
        self.temp = self.final.parent / f".{self.final.name}.partial"
        self.sources: Dict[str, str] = {}
        self.published: List[Path] = []
        self.manifest: Optional[cf.CrateManifest] = None

    def recipients(self) -> List[bytes]:
        identity, recipient = cf.generate()
        self.proof = bytearray(cf.parse_identity(identity))
        del identity
        return [cf.parse_recipient(r) for r in self.plan.recipients] + [cf.parse_recipient(recipient)]

    def stream(self, hashing: _Hashing) -> Any:
        return cf.AgeWriter(hashing, self.recipients()) if self.encrypted else hashing

    def body(self, sink: cf.CrateSink) -> Dict[str, Any]:
        plan, job = self.plan, self.job
        for name in (cf.constants.M_MAGIC, cf.constants.M_README, cf.constants.M_EXTRACT):
            sink.add_member(name, cf.constants.MAGIC if name == cf.constants.M_MAGIC else cf.template_bytes(name))
        rows, entries, lines, line_counts = None, [], 0, {}
        if not self.share:
            job.phase(K.PHASE_ROWS)
            rows = write_rows(sink, plan, job, self.env.state)
            sink.add_member(cf.constants.M_SCHEMA, cf.canonical.dumps(cf.schema_json(rows.tables)))
            self.warnings += rows.warnings + [f"{K.W_ROWS_CHANGED}: {label} {table} has {n} rows now"
                                               for (label, table), n in sorted(rows.counts.items())
                                               if n != plan.row_counts.get((label, table), n)]
            job.phase(K.PHASE_ENTRIES)
            entries, blockers = read_entries(plan.entries, plan.keys, self.env.locations)
            if blockers:
                raise ExportFailed("source_changed", blockers)
        sink.add_member(cf.constants.M_ENTRIES, cf.canonical.dumps({"entries": entries}))
        if not self.share and plan.lines:
            job.phase(K.PHASE_LINES)
            lines, line_counts = write_lines(sink, plan.lines, job)
        files = self.files(sink)
        return {"rows": rows, "entries": entries, "lines": lines, "line_counts": line_counts, "files": files,
                "extra": {**self.project_extra(sink, files), **self.backup_extra()}}

    def backup_extra(self) -> Dict[str, Any]:
        plan = self.plan
        if not plan.request.include_backups and not plan.backup_families:
            return {}
        return {"backup_families": {"conversations": bool(plan.request.include_backups), "folders": [dict(f) for f in plan.backup_families]}}

    def project_extra(self, sink: cf.CrateSink, files: FileWriter) -> Dict[str, Any]:
        """The v1.1 additions of a crate that carries the project's files: the ``project_git`` block of ``crate.json`` and,
        when there are tracked changes, the ``project/uncommitted.patch`` member (scanned for credentials like a file).
        Output: crate.json's extra keys (empty when the crate carries no project files)."""
        if not self.plan.request.include_project_files:
            return {}
        root = str(self.plan.project_root)
        snap = project_git.snapshot(root)
        if snap is None:
            if os.path.lexists(os.path.join(root, ".git")):
                self.warnings.append(f"{K.W_PROJECT_GIT}: git state could not be read for the project folder")
            return {"project_git": None}
        if snap.patch is not None:
            sink.add_member(cf.constants.M_PROJECT_PATCH, snap.patch)
            where = cf.constants.M_PROJECT_PATCH  # project files
            for start in range(0, len(snap.patch), K.MiB):
                for detector, n in cs.scan_counts(snap.patch[start:start + K.MiB].decode("utf-8", "replace")).items():
                    found = files.out.findings.setdefault(where, {})
                    found[detector] = found.get(detector, 0) + n
        self.warnings += snap.warnings
        return {"project_git": snap.block}

    def files(self, sink: cf.CrateSink) -> FileWriter:
        self.job.phase(K.PHASE_FILES, total=sum(f.size for f in self.plan.files), files=len(self.plan.files))
        homes = [str(h) for h in self.env.locations.claude_homes()]
        writer = FileWriter(sink, self.plan, self.job, scan=not self.share,
                            transform=SO.make_transform(self.stats) if self.share else None,
                            place=SO.place if self.share else None,
                            plan_homes=[] if self.share else sorted(set(homes + list(self.plan.homes.claude))))
        writer.set_deny(deny_inodes(self.env.locations))
        for pf in self.plan.files:
            written = writer.write(pf)
            if written is not None:
                writer.add(written, pf)
        for pf in writer.discovered_plans(list(self.plan.homes.claude)):
            writer.add(writer.write_disk(pf), pf)
        self.warnings += writer.out.warnings
        return writer

    def seal(self, sink: cf.CrateSink, parts: Dict[str, Any]) -> cf.CrateManifest:
        plan, out = self.plan, parts["files"].out
        rows = parts["rows"]
        if self.share:
            S.gate_member(cf.constants.M_FILES, [r.as_json() for r in out.records])
        sink.add_member(cf.constants.M_FILES, M.files_jsonl(out.records))
        sink.add_member(cf.constants.M_PATHS, M.paths_jsonl(rows.paths if rows else [], parts["entries"]))
        digest = cs.detectors_digest()
        sink.add_member(cf.constants.M_SECRETS, cf.canonical.dumps(
            SO.secrets_json(self.stats, digest) if self.share else M.secrets_json(out.findings, digest)))
        sink.add_member(cf.constants.M_RECONCILE, cf.canonical.dumps({"artifacts": self.reconcile(parts)}))
        install_id, machine = cs.install_identity(state_dir=self.env.state)
        counts = {"files": len(out.records), "bytes": sum(r.length for r in out.records),
                  "rows": _row_totals(rows), "entries": len(parts["entries"]), "lines": parts["lines"]}
        conversations = (SO.conversation_records(plan, out.harness) if self.share
                         else M.conversation_records(plan, out.harness))
        manifest = M.manifest(
            plan=plan, bundle_id=self.bundle_id, created_epoch=self.epoch,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.epoch)),
            writer=M.writer_block(self.codec, cs.app_version()), source={"install_id": install_id, "machine_label": machine},
            conversations=conversations, members=sink.manifest_members(),
            blobs=sink.blobs_block(), counts=counts, warnings=self.warnings, findings=out.findings,
            extra=parts.get("extra"))
        if self.share:
            manifest = SO.finish(manifest, plan, self.stats, out.skipped)
        sink.add_member(cf.constants.M_MANIFEST, cf.canonical.dumps(manifest.as_json()))
        return manifest

    def reconcile(self, parts: Dict[str, Any]) -> List[Dict[str, Any]]:
        out, rows = parts["files"].out, parts["rows"]
        if self.share:
            agg = SO.reconcile_rows(self.plan, self.plan.files, out.written)
            S.gate_member(cf.constants.M_RECONCILE, agg)
            return agg
        entry_counts: Dict[str, int] = {}
        for entry in parts["entries"]:
            entry_counts[entry["store"]] = entry_counts.get(entry["store"], 0) + 1
        return M.reconcile_rows(self.plan, out.written, rows.counts if rows else {}, entry_counts, parts["line_counts"],
                                out.discovered)


def _row_totals(rows: Any) -> Dict[str, int]:
    totals: Dict[str, int] = {}
    for (label, _table), n in (rows.counts if rows else {}).items():
        totals[crate_store(label)] = totals.get(crate_store(label), 0) + n
    return dict(sorted(totals.items()))


def _replan(env: CrateEnv, plan: ExportPlan, job: JobHandle) -> ExportPlan:
    job.phase(K.PHASE_PLANNING)
    fresh = build_plan(env, plan.request)
    if fresh.fingerprint != plan.fingerprint:
        raise ExportRefused("plan_changed", fresh)
    if not fresh.ok:
        raise ExportRefused("blocked", fresh.blockers)
    return fresh


def _write(run: _Run) -> str:
    run.job.temp(str(run.temp))
    fd = os.open(run.temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, K.FILE_MODE)
    with os.fdopen(fd, "wb") as handle:
        hashing = _Hashing(handle)
        raw = run.stream(hashing)
        sink = cf.CrateSink(raw, run.epoch, run.codec)
        parts = run.body(sink)
        run.job.phase(K.PHASE_SEALING)
        run.manifest = run.seal(sink, parts)
        sink.close()
        if raw is not hashing:
            raw.close()
        handle.flush()
        os.fsync(handle.fileno())
    run.sources = parts["files"].out.source_sha
    return hashing.digest.hexdigest()


def _verify_and_rehash(run: _Run, sha: str) -> cf.VerifyReport:
    run.job.phase(K.PHASE_VERIFYING)
    ids = [bytes(run.proof)] if run.encrypted else []
    report = cf.verify(run.temp, "full", expected_sha256=sha, extra_identities=ids)
    if not report.ok:
        raise ExportFailed("verify_failed", report.codes)
    run.job.phase(K.PHASE_REHASHING, files=len(run.sources))
    for path, want in sorted(run.sources.items()):
        run.job.check()
        try:
            got = rehash(path)
        except OSError as exc:
            raise ExportFailed("source_changed", f"{path} could not be read again ({type(exc).__name__})") from exc
        if got != want:
            raise ExportFailed("source_changed", f"{path} changed after it was copied")
        run.job.add(0, files=1)
    return report


def _publish(run: _Run, sha: str, size: int) -> None:
    run.job.phase(K.PHASE_PUBLISHING)
    run.job.published(record.writer_record(run.plan, run.bundle_id, str(run.final), sha, size, run.epoch))
    try:
        publish(run.temp, run.final)
        run.published.append(run.final)
        run.job.untemp(str(run.temp))
        for name, data in _sidecars(run, sha):
            write_new(run.final.parent / name, data, run.job.temp)
            run.published.append(run.final.parent / name)
            run.job.untemp(str(run.final.parent / f".{name}.partial"))
    except NameTaken as exc:
        raise ExportFailed("name_taken", str(exc)) from exc


def _sidecars(run: _Run, sha: str) -> List[tuple]:
    out = [(f"{run.final.name}.sha256", sha_sidecar(sha, run.final.name))]
    if run.encrypted:
        out.append((f"{run.final.name}.README.txt",
                    age_readme(run.final.name, run.plan.recipients, str(run.env.setting("keyHint", "") or ""))))
    return out


def _second_copy(run: _Run, result: ExportResult) -> None:
    if run.share or not str(run.env.setting("secondFolder", "") or "").strip():
        return
    run.job.phase(K.PHASE_COPYING, total=result.size)
    sidecars = _sidecars(run, result.sha256)
    try:
        second = folders.resolve(run.env, K.FOLDER_SECOND)
        ids = [bytes(run.proof)] if run.encrypted else []
        copied = copy_crate(result.path, second, result.sha256, run.job, identities=ids, sidecars=sidecars)
    except (folders.FolderUnavailable, CopyFailed) as exc:
        result.warnings.append(f"{K.W_SECOND_COPY}: {getattr(exc, 'detail', exc)}")
        return
    except ExportCancelled:
        result.warnings.append(f"{K.W_SECOND_COPY}: the copy was cancelled; the crate is published and recorded in the "
                               "first folder")
        return
    try:
        record.add_location(run.env, result.bundle_id, str(copied), time.time())
    except (sqlite3.Error, sx.MainDbUnreadable, sx.BundleNotFound) as exc:
        for path in [copied] + [copied.parent / name for name, _data in sidecars]:
            if os.path.lexists(path):
                os.unlink(path)
        result.warnings.append(f"{K.W_SECOND_COPY}: the copy could not be recorded ({type(exc).__name__}) and was "
                               "removed")
        return
    result.second = copied


def run_export(env: CrateEnv, plan: ExportPlan, job: JobHandle, *, codec: Optional[str] = None,
               created_epoch: Optional[int] = None, bundle_id: Optional[str] = None) -> ExportResult:
    fresh = _replan(env, plan, job)
    epoch = int(created_epoch if created_epoch is not None else time.time())
    run = _Run(env, fresh, job, codec or bc.default_codec(), epoch,
               bundle_id or mint_bundle_id(fresh.request.variant, fresh.request.scope, epoch))
    try:
        sha = _write(run)
        report = _verify_and_rehash(run, sha)
        _publish(run, sha, report.bytes)
        now = time.time()
        findings = int(run.manifest.secrets.get("findings", 0)) if run.manifest else 0
        result = ExportResult(run.bundle_id, run.final.name, run.final, sha, report.bytes, str(report.content_id),
                              fresh.request.variant, run.encrypted, epoch, findings, now, warnings=list(run.warnings))
        if not run.share:
            job.phase(K.PHASE_RECORDING)
            record.record_own(env, fresh, result, now)
            result.recorded = True
        run.published = []
        _second_copy(run, result)
        return result
    except BaseException:
        for path in run.published:
            if path.exists():
                os.unlink(path)
        raise
    finally:
        for path in list(job.temp_paths):
            if os.path.lexists(path) and os.path.basename(path).endswith(".partial"):
                os.unlink(path)
            job.untemp(path)
        for index in range(len(run.proof)):
            run.proof[index] = 0
        run.proof = bytearray()
