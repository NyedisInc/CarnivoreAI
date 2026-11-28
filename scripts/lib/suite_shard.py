#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SHARD1_ONLY = (
    "tests/python/release/test_notices_cover_payload.py",
    "tests/python/tmux_iopolicy/test_tmux_version_skew.py",
)


def split_files(files: list[str], n: int, serial: list[str], weights: dict[str, float] | None = None,
                capacity: list[float] | None = None) -> list[list[str]]:
    w = weights or {}
    cap = capacity if capacity and len(capacity) == n and all(c > 0 for c in capacity) else [1.0] * n
    shards: list[list[str]] = [[] for _ in range(n)]
    load = [0.0] * n
    for f in sorted(set(files) & set(serial)):
        shards[0].append(f)
        load[0] += w.get(f, 1.0)
    for f in sorted((f for f in set(files) if f not in serial), key=lambda f: (-w.get(f, 1.0), f)):
        i = min(range(n), key=lambda k: ((load[k] + w.get(f, 1.0)) / cap[k], k))
        shards[i].append(f)
        load[i] += w.get(f, 1.0)
    return shards


def group_by_file(ids: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for i in ids:
        out.setdefault(i.split("::", 1)[0], []).append(i)
    return out


def collect_ids(cwd: Path) -> list[str] | None:
    r = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"], cwd=cwd, capture_output=True, text=True)
    ids = [ln.strip() for ln in r.stdout.splitlines() if "::" in ln and not ln.startswith((" ", "=", "-"))]
    return ids if r.returncode == 0 and ids else None


def plan(shard: str, out: Path, durations: str, serial: list[str], cwd: Path) -> int:
    i, n = (int(x) for x in shard.split("/"))
    if not 1 <= i <= n:
        print(f"suite_shard: bad shard {shard}", file=sys.stderr)
        return 90
    ids = collect_ids(cwd)
    if ids is None:
        print("suite_shard: the collection failed; a refusal to run, never a pass", file=sys.stderr)
        return 90
    weights = json.loads(Path(durations).read_text()) if durations and Path(durations).is_file() else None
    by_file = group_by_file(ids)
    capacity = [float(x) for x in os.environ.get("CLOUDE_SHARD_CAPACITY", "").split(",") if x.strip()]
    pinned = list(dict.fromkeys([*serial, *SHARD1_ONLY]))
    mine = split_files(list(by_file), n, pinned, weights, capacity)[i - 1]
    out.mkdir(parents=True, exist_ok=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True).stdout.strip()
    (out / "sha.txt").write_text(sha + "\n")
    (out / "collected-all.txt").write_text("\n".join(ids) + "\n")
    (out / "collected-shard.txt").write_text("\n".join(x for f in mine for x in by_file[f]) + "\n")
    (out / "pass1-files.txt").write_text("".join(f + "\n" for f in mine if f not in serial))
    (out / "pass2-files.txt").write_text("".join(f + "\n" for f in mine if f in serial))
    print(f"suite_shard: shard {shard}: {len(mine)} of {len(by_file)} files, {sum(len(by_file[f]) for f in mine)} of {len(ids)} ids")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["plan"])
    ap.add_argument("--shard", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--durations", default="")
    ap.add_argument("--serial", action="append", default=[])
    a = ap.parse_args(argv)
    return plan(a.shard, Path(a.out), a.durations, a.serial, Path.cwd())


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
