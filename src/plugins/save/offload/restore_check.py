"""Read-only restore test of every offloaded conversation (issue #3398).

ONE JOB: for each conversation in the offload ledger, prove the vault still holds a restorable copy. It opens the ledger JSON, the manifests and
the chunk blobs read only (plain file reads, no ledger or vault object that writes), and optionally restores a sample into a scratch folder.

Per conversation it checks: the pinned point's manifest exists and its digest matches the ledger; every chunk exists, decompresses and matches
its recorded hash and length; each file's whole hash (content or chain kind) and length match the manifest; the file count and total bytes match
the ledger; every JSONL file ends in a whole line, every line is valid JSON and the newline count equals the recorded ``lines``. Whether the
original transcript is still on disk is REPORTED, never a failure.

Usage: python3 src/plugins/save/offload/restore_check.py --scratch DIR [--vault DIR] [--state DIR] [--sample 5] [--seed N]
       [--changed-paths FILE] [--slice MOD REM] [--include-uuids FILE] [--deadline SECONDS] [--left-out FILE]
Subset mode (the nightly USB copy, a hard time cap): any of --changed-paths (vault-relative paths rsync wrote; selects the conversations whose manifest
or chunks they are), --slice (conversations whose index in sorted-uuid order mod MOD equals REM) and --include-uuids (a carried-over list) narrows the
pass to the union; none of them means every conversation. --deadline stops starting new conversations after that many seconds and writes the ones
not reached to --left-out. Exit 3 means a clean but PARTIAL pass.
Output: one JSON document (summary, failures, sample restore results) at ``<scratch>/check-results.json``; a short summary on stdout.
Only uuids, paths and counts are printed, never conversation content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from src.plugins.save.offload.verify import manifest_digest  # noqa: E402
from src.plugins.save.vault import constants as K  # noqa: E402
from src.plugins.save.vault import location, restore  # noqa: E402
from src.plugins.save.vault.chunks import BlobStore  # noqa: E402
from src.plugins.save.vault.manifest import FileEntry, Manifest, ManifestError, ManifestStore  # noqa: E402
from src.plugins.sdk.blob_codec import BlobCorrupt, BlobMissing, CodecUnavailable, chain_sha  # noqa: E402

DEFAULT_STATE = Path.home() / "Library" / "Application Support" / "Carnivore"
KIND_LEDGER = "ledger_row"
KIND_MANIFEST_MISSING = "manifest_missing"
KIND_MANIFEST_DIGEST = "manifest_digest_mismatch"
KIND_FILE_COUNT = "file_count_mismatch"
KIND_BYTES = "bytes_mismatch"
KIND_CHUNK_MISSING = "chunk_missing"
KIND_CHUNK_CORRUPT = "chunk_corrupt"
KIND_HASH = "file_hash_or_size_mismatch"
KIND_JSON = "invalid_json_line"
KIND_TAIL = "no_trailing_newline"
KIND_LINES = "line_count_mismatch"


@dataclass
class Failure:

    uuid: str
    kind: str
    rel: str
    reason: str


@dataclass
class Totals:

    rows: int = 0
    ok: int = 0
    files: int = 0
    raw_bytes: int = 0
    json_lines: int = 0
    original_present: int = 0
    original_partial: int = 0
    original_gone: int = 0
    in_holding: int = 0
    failures: List[Failure] = field(default_factory=list)


def open_json(path: Path) -> Dict[str, Any]:
    with open(path, "rb") as handle:
        return json.loads(handle.read())


def read_chunks(blobs: BlobStore, entry: FileEntry) -> Any:
    for ref in entry.chunks:
        yield blobs.get(ref)


def check_file(blobs: BlobStore, entry: FileEntry, uuid: str, totals: Totals) -> Optional[Failure]:
    digest, total, newlines, tail = hashlib.sha256(), 0, 0, b""
    is_jsonl = entry.rel.endswith(".jsonl") and entry.role in K.LINE_ROLES
    bad_json = 0
    try:
        for raw in read_chunks(blobs, entry):
            digest.update(raw)
            total += len(raw)
            if is_jsonl:
                buf = tail + raw
                parts = buf.split(b"\n")
                tail = parts.pop()
                newlines += len(parts)
                for line in parts:
                    if line.strip():
                        totals.json_lines += 1
                        try:
                            json.loads(line)
                        except ValueError:
                            bad_json += 1
            else:
                newlines += raw.count(b"\n")
    except BlobMissing as exc:
        return Failure(uuid, KIND_CHUNK_MISSING, entry.rel, str(exc))
    except (BlobCorrupt, CodecUnavailable) as exc:
        return Failure(uuid, KIND_CHUNK_CORRUPT, entry.rel, str(exc))
    except OSError as exc:
        return Failure(uuid, KIND_CHUNK_MISSING, entry.rel, f"read error {exc.strerror or exc}")
    whole = digest.hexdigest() if entry.sha_kind == K.SHA_CONTENT else chain_sha(entry.chunks)
    if total != entry.length or whole != entry.sha256:
        return Failure(uuid, KIND_HASH, entry.rel, f"size {total} vs recorded {entry.length}, hash match {whole == entry.sha256}")
    totals.raw_bytes += total
    if bad_json:
        return Failure(uuid, KIND_JSON, entry.rel, f"{bad_json} line(s) are not valid JSON")
    if is_jsonl:
        if tail.strip():
            return Failure(uuid, KIND_TAIL, entry.rel, f"{len(tail)} byte(s) after the last newline")
        if entry.lines and newlines != entry.lines:
            return Failure(uuid, KIND_LINES, entry.rel, f"{newlines} lines vs recorded {entry.lines}")
    return None


def original_state(manifest: Manifest) -> str:
    here = [os.path.exists(f.source_path) for f in manifest.files if f.source_path]
    if not here:
        return "gone"
    return "present" if all(here) else ("partial" if any(here) else "gone")


def check_conversation(row: Dict[str, Any], manifests: ManifestStore, blobs: BlobStore, totals: Totals) -> Optional[Manifest]:
    uuid = str(row.get("conversation_id", "?"))
    before = len(totals.failures)
    try:
        manifest = manifests.read(str(row["unit"]), str(row["point_id"]))
    except (KeyError, ManifestError) as exc:
        totals.failures.append(Failure(uuid, KIND_MANIFEST_MISSING, "", str(exc)[:200]))
        return None
    if manifest_digest(manifest) != row.get("manifest_sha256"):
        totals.failures.append(Failure(uuid, KIND_MANIFEST_DIGEST, "", "the point's file list digest differs from the ledger"))
    if len(manifest.files) != row.get("files"):
        totals.failures.append(Failure(uuid, KIND_FILE_COUNT, "", f"{len(manifest.files)} in the point vs {row.get('files')} in the ledger"))
    if manifest.raw_bytes() != row.get("bytes"):
        totals.failures.append(Failure(uuid, KIND_BYTES, "", f"{manifest.raw_bytes()} in the point vs {row.get('bytes')} in the ledger"))
    for entry in manifest.files:
        totals.files += 1
        failed = check_file(blobs, entry, uuid, totals)
        if failed:
            totals.failures.append(failed)
    state = original_state(manifest)
    totals.original_present += state == "present"
    totals.original_partial += state == "partial"
    totals.original_gone += state == "gone"
    totals.in_holding += bool(row.get("holding_dir") and os.path.isdir(row["holding_dir"]))
    if len(totals.failures) == before:
        totals.ok += 1
    return manifest


def pick_sample(rows: Sequence[Dict[str, Any]], count: int, seed: int) -> List[Dict[str, Any]]:
    if count <= 0 or not rows:
        return []
    ordered = sorted(rows, key=lambda r: r["bytes"])
    chosen = [ordered[-1], ordered[0]]
    rest = [r for r in ordered[1:-1]]
    chosen += random.Random(seed).sample(rest, max(0, min(count - 2, len(rest))))
    return chosen


def compare_restored(blobs: BlobStore, manifest: Manifest, root: Path) -> Dict[str, Any]:
    result = restore.restore_to_root(blobs, manifest, root)
    vault_same = original_same = original_checked = 0
    mismatched: List[str] = []
    for entry in manifest.files:
        dest = root / entry.home / entry.rel
        wanted = hashlib.sha256()
        for raw in read_chunks(blobs, entry):
            wanted.update(raw)
        got = hashlib.sha256(dest.read_bytes()).hexdigest()
        if got == wanted.hexdigest() and dest.stat().st_size == entry.length:
            vault_same += 1
        else:
            mismatched.append(f"{entry.rel}: differs from the vault bytes")
        if entry.source_path and os.path.isfile(entry.source_path):
            original_checked += 1
            if hashlib.sha256(Path(entry.source_path).read_bytes()).hexdigest() == got:
                original_same += 1
            else:
                mismatched.append(f"{entry.rel}: differs from the original (the original may have grown since)")
    return {"written": len(result.written), "files": len(manifest.files), "same_as_vault": vault_same,
            "original_compared": original_checked, "same_as_original": original_same, "notes": mismatched}


def permissions_report(vault: Path, state: Path, rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    report: Dict[str, Any] = {"vault_realpath": os.path.realpath(vault)}
    for name in ("", "blobs", "manifests", "vault-offload.json", "vault-offload.json.prev"):
        path = vault / name if name else vault
        report[f"mode:{name or '.'}"] = oct(stat.S_IMODE(os.stat(path).st_mode))
    counts = {"files": 0, "world_readable_files": 0, "world_readable_dirs": 0, "bytes": 0}
    for sub in ("blobs", "manifests"):
        for folder, dirs, files in os.walk(vault / sub):
            counts["world_readable_dirs"] += sum(1 for d in dirs if os.stat(os.path.join(folder, d)).st_mode & stat.S_IROTH)
            for name in files:
                info = os.stat(os.path.join(folder, name))
                counts["files"] += 1
                counts["bytes"] += info.st_size
                counts["world_readable_files"] += bool(info.st_mode & stat.S_IROTH)
    report["walk"] = counts
    holding = [r["holding_dir"] for r in rows if r.get("holding_dir")]
    report["holding_dirs"] = {d: oct(stat.S_IMODE(os.stat(d).st_mode)) for d in holding if os.path.isdir(d)}
    real = os.path.realpath(vault)
    report["vault_in_icloud"] = "Mobile Documents" in real or "CloudStorage" in real or "iCloud" in real
    report["vault_on_volumes"] = real.startswith("/Volumes/")
    report["state_realpath"] = os.path.realpath(state)
    return report


EXIT_PARTIAL = 3


def read_lines(path: Optional[Path]) -> List[str]:
    if path is None or not path.is_file():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rows_for_changed_paths(rows: Sequence[Dict[str, Any]], manifests: ManifestStore, changed: Sequence[str]) -> List[str]:
    blob_shas = {Path(p).name.split(".")[0] for p in changed if p.startswith("blobs/")}
    manifest_paths = {p for p in changed if p.startswith("manifests/")}
    picked: List[str] = []
    for row in rows:
        uuid = str(row.get("conversation_id", "?"))
        if f"manifests/{row.get('unit')}/{row.get('point_id')}.json" in manifest_paths:
            picked.append(uuid)
            continue
        try:
            manifest = manifests.read(str(row["unit"]), str(row["point_id"]))
        except (KeyError, ManifestError):
            picked.append(uuid)
            continue
        if blob_shas and not blob_shas.isdisjoint(manifest.chunk_hashes()):
            picked.append(uuid)
    return picked


def select_rows(rows: Sequence[Dict[str, Any]], manifests: ManifestStore, args: argparse.Namespace) -> List[Dict[str, Any]]:
    if not (args.changed_paths or args.slice or args.include_uuids):
        return list(rows)
    by_uuid = {str(r["conversation_id"]): r for r in sorted(rows, key=lambda r: str(r["conversation_id"]))}
    ordered: List[str] = []
    if args.changed_paths:
        ordered += rows_for_changed_paths(rows, manifests, read_lines(args.changed_paths))
    ordered += [u for u in read_lines(args.include_uuids) if u in by_uuid]
    if args.slice:
        modulus, remainder = args.slice
        ordered += [u for i, u in enumerate(by_uuid) if i % modulus == remainder]
    return [by_uuid[u] for u in dict.fromkeys(ordered) if u in by_uuid]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--sample", type=int, default=5)
    parser.add_argument("--seed", type=int, default=20261127)
    parser.add_argument("--changed-paths", type=Path, default=None, help="file of vault-relative paths rsync wrote")
    parser.add_argument("--slice", type=int, nargs=2, metavar=("MOD", "REM"), default=None)
    parser.add_argument("--include-uuids", type=Path, default=None, help="file of uuids to verify as well")
    parser.add_argument("--deadline", type=float, default=None, help="stop starting conversations after this many seconds")
    parser.add_argument("--left-out", type=Path, default=None, help="where to write uuids not reached before the deadline")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        vault = args.vault or location.resolve_root(args.state)
        ledger = open_json(vault / K.OFFLOAD_FILE)
        rows = list(ledger["conversations"].values())
    except (OSError, ValueError, KeyError) as exc:
        print(f"cannot read the ledger: {exc}", file=sys.stderr)
        return 2
    manifests, blobs, totals = ManifestStore(vault), BlobStore(vault), Totals()
    started, loaded = time.time(), {}
    selected = select_rows(rows, manifests, args)
    left_out: List[str] = []
    for row in selected:
        if args.deadline is not None and time.time() - started > args.deadline:
            left_out.append(str(row["conversation_id"]))
            continue
        totals.rows += 1
        loaded[row["conversation_id"]] = check_conversation(row, manifests, blobs, totals)
    if args.left_out:
        args.left_out.parent.mkdir(parents=True, exist_ok=True)
        args.left_out.write_text("".join(f"{u}\n" for u in left_out), encoding="utf-8")
    args.scratch.mkdir(parents=True, exist_ok=True)
    samples: List[Dict[str, Any]] = []
    for row in pick_sample([r for r in rows if loaded.get(r["conversation_id"])], args.sample, args.seed):
        folder = args.scratch / "restored" / row["conversation_id"]
        try:
            outcome = compare_restored(blobs, loaded[row["conversation_id"]], folder)
        except (restore.RestoreError, OSError) as exc:
            outcome = {"error": str(exc)[:200]}
        samples.append({"uuid": row["conversation_id"], "bytes": row["bytes"], "files": row["files"], **outcome})
    out = {"vault": str(vault), "seconds": round(time.time() - started, 1), "rows": totals.rows, "ok": totals.ok,
           "files": totals.files, "selected": len(selected), "left_out": len(left_out), "raw_bytes": totals.raw_bytes, "json_lines": totals.json_lines,
           "original_present": totals.original_present, "original_partial": totals.original_partial,
           "original_gone": totals.original_gone, "still_in_holding": totals.in_holding,
           "failures": [f.__dict__ for f in totals.failures], "samples": samples,
           "security": permissions_report(vault, args.state, rows)}
    (args.scratch / "check-results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("failures", "samples", "security")}), f"failures={len(totals.failures)}")
    if totals.failures:
        return 1
    return EXIT_PARTIAL if left_out else 0


if __name__ == "__main__":
    sys.exit(main())
