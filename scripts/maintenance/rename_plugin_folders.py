#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, FrozenSet, Iterable, List, Optional, Protocol, Sequence, Tuple, cast

from scripts.maintenance import huddle_rename_rules
from scripts.maintenance import plugin_rename_rules as rules



class RuleSet(Protocol):

    FOLDER_MOVES: Tuple[Tuple[str, str], ...]

    def is_excluded(self, path: str) -> bool:
        pass

    def new_path(self, path: str) -> str:
        pass

    def old_path(self, path: str) -> str:
        pass

    def in_old_folder(self, path: str) -> bool:
        pass

    def web_children(self, files: Iterable[str]) -> FrozenSet[str]:
        pass

    def apply_text_rules(self, path: str, text: str, counts: Dict[str, int], children: FrozenSet[str] = frozenset()) -> str:
        pass

    def leftover_hits(self, path: str, text: str, children: FrozenSet[str] = frozenset()) -> List[str]:
        pass

    def invariant_counts(self, texts: Iterable[str]) -> Dict[str, int]:
        pass


RULE_SETS: Dict[str, RuleSet] = {"folders": cast(RuleSet, rules), "huddle": cast(RuleSet, huddle_rename_rules)}
DEFAULT_RULES: RuleSet = RULE_SETS["folders"]

EXIT_OK, EXIT_REFUSED, EXIT_CANNOT = 0, 1, 2
MAX_CHECK_LINES = 60


class RenameError(Exception):
    pass


class GitError(Exception):
    pass


@dataclass
class Plan:

    dir_moves: List[Tuple[str, str]] = field(default_factory=list)
    file_moves: List[Tuple[str, str]] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    rewrites: Dict[str, str] = field(default_factory=dict)
    rule_counts: Counter = field(default_factory=Counter)
    folder_counts: Counter = field(default_factory=Counter)

    def is_empty(self) -> bool:
        return not (self.dir_moves or self.file_moves or self.rewrites or self.conflicts)


def git(root: Path, *args: str, stdin: Optional[bytes] = None) -> bytes:
    try:
        done = subprocess.run(["git", "-C", str(root), *args], input=stdin, capture_output=True, check=False)
    except OSError as exc:
        raise GitError(f"cannot run git: {exc}") from exc
    if done.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} failed: {done.stderr.decode(errors='replace').strip()[:300]}")
    return done.stdout


def tracked_files(root: Path) -> List[str]:
    return [p for p in git(root, "ls-files", "-z").decode("utf-8", "surrogateescape").split("\0") if p]


def ensure_clean(root: Path, rs: RuleSet = DEFAULT_RULES) -> None:
    dirty = git(root, "status", "--porcelain", "--untracked-files=no").decode("utf-8", "replace").strip()
    if dirty:
        first = dirty.splitlines()[:5]
        raise RenameError("refusing a dirty tree (commit or stash your changes first):\n  " + "\n  ".join(first))
    stray = git(root, "ls-files", "-o", "--exclude-standard", "-z", "--", *[old for old, _ in rs.FOLDER_MOVES]).decode("utf-8", "replace")
    if stray:
        names = [p for p in stray.split("\0") if p][:5]
        raise RenameError("refusing: untracked files under an old plugin folder (add or move them first):\n  " + "\n  ".join(names))


def read_text(root: Path, rel: str) -> Optional[str]:
    path = root / rel
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > rules.MAX_TEXT_BYTES:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def plan_moves(root: Path, files: Sequence[str], plan: Plan, rs: RuleSet = DEFAULT_RULES) -> None:
    tracked = set(files)
    for old, new in rs.FOLDER_MOVES:
        under = [f for f in files if f.startswith(old + "/")]
        if not under:
            continue
        if not (root / new).exists():
            plan.dir_moves.append((old, new))
            continue
        for f in under:
            dest = new + f[len(old):]
            if dest in tracked or (root / dest).exists():
                plan.conflicts.append(f"{f} -> {dest} (destination exists)")
            else:
                plan.file_moves.append((f, dest))


def plan_rewrites(root: Path, files: Sequence[str], plan: Plan, rs: RuleSet = DEFAULT_RULES) -> Tuple[Dict[str, int], Dict[str, int]]:
    before_texts: List[str] = []
    after_texts: List[str] = []
    children = rs.web_children(files)
    for rel in files:
        if rs.is_excluded(rel) or rs.is_excluded(rs.old_path(rel)):
            continue
        text = read_text(root, rel)
        if text is None:
            continue
        counts: Dict[str, int] = {}
        rewritten = rs.apply_text_rules(rs.old_path(rel), text, counts, children)
        before_texts.append(text)
        after_texts.append(rewritten)
        if rewritten != text:
            plan.rewrites[rel] = rewritten
            plan.rule_counts.update(counts)
            plan.folder_counts[PurePosixPath(rs.new_path(rs.old_path(rel))).parts[0]] += 1
    return rs.invariant_counts(before_texts), rs.invariant_counts(after_texts)


def build_plan(root: Path, rs: RuleSet = DEFAULT_RULES) -> Plan:
    files = tracked_files(root)
    plan = Plan()
    plan_moves(root, files, plan, rs)
    before, after = plan_rewrites(root, files, plan, rs)
    moved = [n for n in before if before[n] != after[n]]
    if moved:
        detail = ", ".join(f"{n}: {before[n]} -> {after[n]}" for n in moved)
        raise RenameError(f"a rule changed a stored or field-visible name, nothing written ({detail})")
    return plan


def remove_empty_dirs(root: Path, rel: str) -> int:
    removed = 0
    base = root / rel
    if not base.is_dir():
        return 0
    for dirpath, _dirs, _names in os.walk(base, topdown=False):
        try:
            os.rmdir(dirpath)
            removed += 1
        except OSError:
            continue
    return removed


def apply_plan(root: Path, plan: Plan, rs: RuleSet = DEFAULT_RULES) -> None:
    for old, new in plan.dir_moves:
        git(root, "mv", old, new)
    for src, dest in plan.file_moves:
        (root / dest).parent.mkdir(parents=True, exist_ok=True)
        git(root, "mv", src, dest)
    for old, _new in rs.FOLDER_MOVES:
        remove_empty_dirs(root, old)
    written: List[str] = []
    for rel, text in plan.rewrites.items():
        target = rs.new_path(rel)
        (root / target).write_text(text, encoding="utf-8")
        written.append(target)
    if written:
        git(root, "add", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(written).encode("utf-8"))


def find_leftovers(root: Path, rs: RuleSet = DEFAULT_RULES) -> List[str]:
    found: List[str] = []
    files = tracked_files(root)
    children = rs.web_children(files)
    for rel in files:
        if rs.in_old_folder(rel):
            found.append(f"{rel}: still inside the old folder")
        if rs.is_excluded(rel):
            continue
        text = read_text(root, rel)
        if text is not None:
            found += [f"{rel}: {hit}" for hit in rs.leftover_hits(rel, text, children)]
    return found


def report(plan: Plan, dry_run: bool) -> None:
    verb = "would" if dry_run else "did"
    for old, new in plan.dir_moves:
        print(f"{verb} move folder {old} -> {new}")
    if plan.file_moves:
        print(f"{verb} move {len(plan.file_moves)} straggler file(s) into the new folders")
    print(f"{verb} rewrite {len(plan.rewrites)} file(s)")
    for name, n in sorted(plan.rule_counts.items()):
        print(f"  rule {name}: {n}")
    for top, n in sorted(plan.folder_counts.items()):
        print(f"  folder {top}: {n} file(s)")


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Rename src/cplugs -> src/plugins and web/src/cplugs -> web/src/plugins on any tree.")
    ap.add_argument("--root", default=".", help="a folder inside the repo (default: the current folder)")
    ap.add_argument("--rules", choices=sorted(RULE_SETS), default="folders",
                    help="which rename: folders (src/cplugs to src/plugins, #2948) or huddle (the Task Manager id to taskmanager, #3260)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print counts per rule and per folder; write nothing")
    mode.add_argument("--check", action="store_true", help="exit 1 if any old code-path reference remains")
    mode.add_argument("--fixup", action="store_true", help="merge fix-up: requires the new folders to exist, moves stragglers")
    return ap.parse_args(list(argv))


def run(args: argparse.Namespace) -> int:
    root = Path(git(Path(args.root), "rev-parse", "--show-toplevel").decode().strip())
    rs = RULE_SETS[args.rules]
    if args.check:
        left = find_leftovers(root, rs)
        for line in left[:MAX_CHECK_LINES]:
            print(line)
        print(f"check: {len(left)} old code-path reference(s) remain" if left else "check: clean, no old code-path reference remains")
        return EXIT_REFUSED if left else EXIT_OK
    if args.fixup and not all((root / new).is_dir() for _, new in rs.FOLDER_MOVES):
        raise RenameError("--fixup needs both new folders to exist (merge the renamed branch first)")
    plan = build_plan(root, rs)
    if plan.is_empty():
        print("nothing to do: the folders are already renamed and no old reference remains")
        return EXIT_OK
    if plan.conflicts:
        raise RenameError("would overwrite existing files, nothing changed:\n  " + "\n  ".join(plan.conflicts[:20]))
    if not args.dry_run:
        ensure_clean(root, rs)
        apply_plan(root, plan, rs)
    report(plan, args.dry_run)
    return EXIT_OK


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return run(parse_args(sys.argv[1:] if argv is None else argv))
    except RenameError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except GitError as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return EXIT_CANNOT


if __name__ == "__main__":
    sys.exit(main())
