from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "tests" / "fixtures" / "error_log_thin_baseline.json"
SRC = REPO / "src"
LOGGER_NAMES = frozenset({"logger", "log"})


def is_thin_error_call(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "error"):
        return False
    receiver = node.func.value
    if not (isinstance(receiver, ast.Name) and receiver.id in LOGGER_NAMES):
        return False
    if len(node.args) != 1 or len(node.keywords) != 1:
        return False
    only = node.keywords[0]
    value = only.value
    return (
        only.arg == "error"
        and isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "str"
    )


def count_thin(source: str) -> int:
    return sum(1 for node in ast.walk(ast.parse(source)) if is_thin_error_call(node))


def scan(root: Path = SRC, repo: Path = REPO) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(root.rglob("*.py")):
        try:
            found = count_thin(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if found:
            counts[path.relative_to(repo).as_posix()] = found
    return counts


def over_baseline(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    return [f"{path}: {n} > {baseline.get(path, 0)}" for path, n in sorted(counts.items()) if n > baseline.get(path, 0)]


def stale_known(counts: dict[str, int], baseline: dict[str, int]) -> list[str]:
    return [f"{path}: baseline {allowed}, found {counts.get(path, 0)}" for path, allowed in sorted(baseline.items()) if counts.get(path, 0) < allowed]


def staged_paths(repo: Path = REPO) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMR"],
        check=True, capture_output=True,
    ).stdout.decode("utf-8", "surrogateescape")
    return [p for p in out.split("\0") if p.startswith("src/") and p.endswith(".py")]


def scan_staged(repo: Path = REPO) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in staged_paths(repo):
        blob = subprocess.run(["git", "-C", str(repo), "show", f":{path}"], check=True, capture_output=True).stdout
        try:
            found = count_thin(blob.decode("utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if found:
            counts[path] = found
    return counts


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    staged = "--staged" in args
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    try:
        counts = scan_staged() if staged else scan()
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"thin error log guard could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    over = over_baseline(counts, baseline)
    stale = [] if staged else stale_known(counts, baseline)
    for line in over:
        print(f"thin error log: {line}; add error_type, exc_info and the ids in scope")
    for line in stale:
        print(f"thin error log KNOWN entry is stale: {line}; lower or remove it in tests/fixtures/error_log_thin_baseline.json")
    return 1 if over or stale else 0


if __name__ == "__main__":
    sys.exit(main())
