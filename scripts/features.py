#!/usr/bin/env python3
"""Feature catalog and per-change log: validate ``features/``, render the
generated outputs, and add one change entry.

WHY THIS EXISTS (issue #816). Nothing in the repo recorded what the product
does or what changed release by release. This is a conflict-free, fragment-
file catalog: a PR adds small JSON files under ``features/catalog/`` (the
product's current state) and ``features/changes/`` (one immutable entry per
PR, added or fixed or internal) and never edits a shared file. The shared
outputs, ``FEATURES.md``, ``features/index.json`` and ``features/schema.json``,
are GENERATED, only at merge time on master (``scripts/dist-at-merge.sh``),
never committed on a branch.

Stdlib only, so this runs under the system ``python3`` in any worktree.

Subcommands:
    check [--branch]   validate every JSON file, plus media and capture specs
                        (``scripts/features_media.py``). ``--branch`` also
                        enforces that a product-path diff carries a new
                        change file, that a changed catalog file bumped
                        ``updated``, and that an added/changed feature is
                        shown: where, how_to, examples and media (#846).
    render              write FEATURES.md, features/index.json, schema.json.
    new-change          write one features/changes/<date>-<pr>-<slug>.json.

Exit codes, every subcommand: 0 pass, 1 a violation was found, 2 could not
determine (the environment could not be evaluated - not 0, not a pass).

Examples:
    python3 scripts/features.py check
    python3 scripts/features.py check --branch
    python3 scripts/features.py render
    python3 scripts/features.py new-change --type fixed \\
        --features session-restart --summary "fix the thing" --pr 999
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from scripts.lib.trunk_remote import TrunkRemoteError, trunk_remote_name  # noqa: E402
from scripts.features_schema import (  # noqa: E402
    AREA_FIELDS,
    CATALOG_FIELDS,
    CHANGE_FIELDS,
    CHANGE_TYPES,
    DATE_RX,
    build_schema,
    validate_record,
)
from scripts.features_media import check_branch_media, validate_media  # noqa: E402

FEATURES_DIR = REPO / "features"
AREAS_FILE = FEATURES_DIR / "areas.json"
CATALOG_DIR = FEATURES_DIR / "catalog"
CHANGES_DIR = FEATURES_DIR / "changes"
SCHEMA_FILE = FEATURES_DIR / "schema.json"
INDEX_FILE = FEATURES_DIR / "index.json"
FEATURES_MD = REPO / "FEATURES.md"

PRODUCT_PREFIXES = ("src/", "web/src/", "macOS/")


def _is_product_path(path: str) -> bool:
    if path.startswith("client/"):
        return not path.startswith("client/dist/")
    return path.startswith(PRODUCT_PREFIXES)


def _load_json(path: Path) -> tuple[Any, str | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, f"cannot read: {exc}"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


def load_areas() -> tuple[list[dict], list[str]]:
    if not AREAS_FILE.is_file():
        return [], [f"{AREAS_FILE.relative_to(REPO)}: missing"]
    data, err = _load_json(AREAS_FILE)
    rel = AREAS_FILE.relative_to(REPO).as_posix()
    if err:
        return [], [f"{rel}: {err}"]
    if not isinstance(data, list):
        return [], [f"{rel}: must be a JSON array"]
    errors: list[str] = []
    seen: set[str] = set()
    areas: list[dict] = []
    for i, area in enumerate(data):
        where = f"{rel}[{i}]"
        if not isinstance(area, dict):
            errors.append(f"{where}: must be an object")
            continue
        errors.extend(validate_record(area, AREA_FIELDS, where))
        aid = area.get("id")
        if isinstance(aid, str):
            if aid in seen:
                errors.append(f"{where}: duplicate area id '{aid}'")
            else:
                seen.add(aid)
                areas.append(area)
    return areas, errors


def load_catalog(area_ids: set[str]) -> tuple[dict[str, dict], list[str]]:
    catalog: dict[str, dict] = {}
    errors: list[str] = []
    if not CATALOG_DIR.is_dir():
        return catalog, errors
    for path in sorted(CATALOG_DIR.glob("*.json")):
        where = path.relative_to(REPO).as_posix()
        data, err = _load_json(path)
        if err:
            errors.append(f"{where}: {err}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{where}: must be a JSON object")
            continue
        errors.extend(validate_record(data, CATALOG_FIELDS, where))
        eid = data.get("id")
        if isinstance(eid, str) and eid != path.stem:
            errors.append(f"{where}: id {eid!r} does not match filename '{path.stem}.json'")
        area = data.get("area")
        if isinstance(area, str) and area not in area_ids:
            errors.append(f"{where}: area {area!r} is not listed in features/areas.json")
        if isinstance(eid, str):
            if eid in catalog:
                errors.append(f"{where}: duplicate catalog id {eid!r}")
            else:
                catalog[eid] = data
    return catalog, errors


def load_changes(catalog_ids: set[str]) -> tuple[list[tuple[Path, dict]], list[str]]:
    changes: list[tuple[Path, dict]] = []
    errors: list[str] = []
    if not CHANGES_DIR.is_dir():
        return changes, errors
    for path in sorted(CHANGES_DIR.glob("*.json")):
        where = path.relative_to(REPO).as_posix()
        data, err = _load_json(path)
        if err:
            errors.append(f"{where}: {err}")
            continue
        if not isinstance(data, dict):
            errors.append(f"{where}: must be a JSON object")
            continue
        errors.extend(validate_record(data, CHANGE_FIELDS, where))
        features = data.get("features")
        if isinstance(features, list):
            if not features and data.get("type") != "internal":
                errors.append(f"{where}: 'features' must be non-empty unless type is 'internal'")
            for fid in features:
                if isinstance(fid, str) and fid not in catalog_ids:
                    errors.append(f"{where}: references unknown feature id {fid!r}")
        changes.append((path, data))
    return changes, errors


def _load_all() -> tuple[list[dict], dict[str, dict], list[tuple[Path, dict]], list[str]]:
    areas, area_errors = load_areas()
    area_ids = {a["id"] for a in areas if isinstance(a.get("id"), str)}
    catalog, cat_errors = load_catalog(area_ids)
    changes, chg_errors = load_changes(set(catalog))
    media_errors = validate_media(FEATURES_DIR, catalog, REPO)
    return areas, catalog, changes, area_errors + cat_errors + chg_errors + media_errors


def _git(repo: Path, *args: str, stdin_text: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, input=stdin_text)


def _git_strict(repo: Path, *args: str, stdin_text: str | None = None) -> str:
    done = _git(repo, *args, stdin_text=stdin_text)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed ({done.returncode}): {done.stderr.strip()}")
    return done.stdout


def _branch_reference_date(repo: Path) -> str:
    dirty = _git(repo, "status", "--porcelain").stdout.strip()
    if not dirty:
        stamp = _git(repo, "log", "-1", "--format=%ct", "HEAD").stdout.strip()
        if stamp.isdigit():
            return datetime.fromtimestamp(int(stamp), timezone.utc).date().isoformat()
    return datetime.now(timezone.utc).date().isoformat()


def _diff_paths(repo: Path, base: str) -> list[str]:
    def names(*args: str) -> set[str]:
        done = _git(repo, *args, "-z")
        if done.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        return {p for p in done.stdout.split("\0") if p}

    paths = names("diff", "--name-only", f"{base}...HEAD")
    paths |= names("diff", "--name-only", "HEAD")
    paths |= names("ls-files", "--others", "--exclude-standard")
    return sorted(paths)


def _check_branch_rules(repo: Path) -> int:
    try:
        remote = trunk_remote_name(repo)
    except TrunkRemoteError as exc:
        print(f"features.py check --branch: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    base = f"{remote}/master"
    current = _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD").stdout.strip()
    if current == "master":
        print("features.py check --branch: CANNOT DETERMINE - on master, nothing to prove", file=sys.stderr)
        return 2
    if _git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}").returncode != 0:
        print(f"features.py check --branch: CANNOT DETERMINE - base ref {base} does not resolve (git fetch?)",
              file=sys.stderr)
        return 2
    merge_base = _git(repo, "merge-base", "HEAD", base).stdout.strip()
    if not merge_base:
        print(f"features.py check --branch: CANNOT DETERMINE - no merge base with {base}", file=sys.stderr)
        return 2
    try:
        paths = _diff_paths(repo, base)
    except RuntimeError as exc:
        print(f"features.py check --branch: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2

    product_touched = [p for p in paths if _is_product_path(p)]
    change_files = [p for p in paths if p.startswith("features/changes/") and p.endswith(".json")]
    if product_touched and not change_files:
        print("features.py check --branch: VIOLATION - product path(s) changed with no "
              "features/changes/ entry:", file=sys.stderr)
        for p in product_touched[:10]:
            print(f"  {p}", file=sys.stderr)
        print("Add one, e.g.:", file=sys.stderr)
        print("  python3 scripts/features.py new-change --type fixed --features <catalog-id> "
              "--summary \"<one line>\" --pr <N>", file=sys.stderr)
        return 1

    stale = []
    today = None
    for p in paths:
        if not (p.startswith("features/catalog/") and p.endswith(".json")):
            continue
        old = _git(repo, "show", f"{merge_base}:{p}")
        if old.returncode != 0:
            continue
        new_path = repo / p
        if not new_path.is_file():
            continue
        try:
            old_updated = json.loads(old.stdout).get("updated")
            new_updated = json.loads(new_path.read_text(encoding="utf-8")).get("updated")
        except json.JSONDecodeError:
            continue
        if old_updated == new_updated:
            if today is None:
                today = _branch_reference_date(repo)
            if new_updated != today:
                stale.append(p)
    if stale:
        print("features.py check --branch: VIOLATION - catalog file(s) changed with no "
              "'updated' date bump (unchanged from the merge base and not today):", file=sys.stderr)
        for p in stale:
            print(f"  {p}", file=sys.stderr)
        return 1

    catalog, _errors = load_catalog({a["id"] for a in load_areas()[0] if isinstance(a.get("id"), str)})
    shown = check_branch_media(repo, paths, catalog)
    if shown:
        print("features.py check --branch: VIOLATION - a feature this branch adds or changes "
              "is not shown (issue #846):", file=sys.stderr)
        for line in shown:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(f"features.py check --branch: OK against {base}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    _areas, _catalog, _changes, errors = _load_all()
    if errors:
        for e in errors:
            print(f"features.py check: {e}", file=sys.stderr)
        print(f"features.py check: {len(errors)} violation(s)", file=sys.stderr)
        return 1
    if args.branch:
        rc = _check_branch_rules(REPO)
        if rc != 0:
            return rc
    print(f"features.py check: OK ({len(_areas)} area(s), {len(_catalog)} catalog entry/ies, "
          f"{len(_changes)} change(s))")
    return 0


def _version_key(tag: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", tag)
    return tuple(int(p) for p in parts) if parts else (0,)


def _added_commit(repo: Path, path: Path) -> str | None:
    lines = [line for line in _git_strict(repo, "log", "--follow", "--format=%H", "--", str(path)).splitlines() if line.strip()]
    return lines[-1] if lines else None


def _landed_at(repo: Path, commit: str) -> str | None:
    text = _git_strict(repo, "log", "-1", "--format=%ct", commit).strip()
    if not text.isdigit():
        return None
    return datetime.fromtimestamp(int(text), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _release_for(repo: Path, commit: str, version_tags: list[str]) -> str:
    containing = {t for t in _git_strict(repo, "tag", "--list", "v*", "--contains", commit).splitlines() if t.strip()}
    for tag in version_tags:
        if tag in containing:
            return tag
    return "Unreleased"


def _added_commits(repo: Path, paths: list[Path]) -> tuple[dict[Path, tuple[str, int]], set[Path]]:
    rel = {p.relative_to(repo).as_posix(): p for p in paths}
    dirs = sorted({str(Path(r).parent) for r in rel})
    out = _git_strict(repo, "log", "--full-history", "-C", "--find-copies-harder", "--name-status", "--format=%x00%H %ct", "--", *dirs)
    origin = {r: [p] for r, p in rel.items()}
    found: dict[Path, tuple[str, int]] = {}
    ended_on_add: dict[Path, str] = {}
    for block in out.split("\0")[1:]:
        head, _, body = block.partition("\n")
        sha, _, ct = head.partition(" ")
        stamp = (sha, int(ct)) if ct.strip().isdigit() else None
        for line in body.splitlines():
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            names = cols[1:]
            targets = origin.get(names[-1], ())
            for target in targets:
                if stamp:
                    found[target] = stamp
                if cols[0][0] == "A":
                    ended_on_add[target] = sha
                else:
                    ended_on_add.pop(target, None)
                if cols[0][0] in "RC":
                    origin.setdefault(names[0], []).append(target)
    candidates = set(ended_on_add.values())
    outside: set[Path] = set()
    if candidates:
        tree = _git_strict(repo, "diff-tree", "--stdin", "-r", "-M", "--name-status", "--no-commit-id", "--root", stdin_text="\n".join(sorted(candidates)) + "\n")
        renamed_in = set()
        for line in tree.splitlines():
            cols = line.split("\t")
            if len(cols) == 3 and cols[0][0] == "R" and cols[2] in rel and str(Path(cols[1]).parent) not in dirs:
                renamed_in.add(rel[cols[2]])
        outside = renamed_in & ended_on_add.keys()
    return found, outside


def _release_map(repo: Path, commits: set[str], version_tags: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    left = set(commits)
    for tag in version_tags:
        if not left:
            break
        reach = set(_git_strict(repo, "rev-list", tag).split())
        for c in left & reach:
            out[c] = tag
        left -= reach
    return out


def _package_json_version(repo: Path) -> str | None:
    path = repo / "macOS" / "package.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            version = json.load(handle).get("version")
    except (OSError, ValueError):
        return None
    if not isinstance(version, str) or not version.strip():
        return None
    return version.strip().lstrip("vV").strip()


def _pending_release_tag(repo: Path, version_tags: list[str]) -> str | None:
    """The release name a currently-untagged commit belongs to, if one is pending.

    Root cause (issue reported against v1.12.18, reproduced back through
    v1.12.16): a release is cut by (1) bumping ``macOS/package.json``'s
    version, (2) letting ``scripts/dist-at-merge.sh`` regenerate and commit
    ``features/index.json`` on that tip, THEN (3) tagging the tip ``vX.Y.Z``.
    ``_release_for`` only ever answers with a tag that already exists, so at
    step 2 the tag from step 3 is not there yet, and every change since the
    previous tag - including the release's own - is stamped "Unreleased"
    into the very ``index.json`` that ships inside that tag, permanently
    (nothing re-renders after the tag lands).

    Fix: once ``macOS/package.json``'s version has moved past every existing
    ``v*`` tag (the bump from step 1 has landed) but no tag matches it yet
    (step 3 has not happened), that version is already decided - so treat it
    as the bucket for anything that would otherwise fall through to
    "Unreleased", instead of "Unreleased" itself. Once the tag is actually
    pushed, ``_release_for`` finds it directly and this function is never
    consulted for those commits again.

    Returns:
        ``"vX.Y.Z"`` when a bump is pending and not yet tagged, else
        ``None`` (no package.json version, or it is already tagged, or it is
        not ahead of the newest existing tag).
    """
    version = _package_json_version(repo)
    if version is None:
        return None
    pending_tag = f"v{version}"
    if pending_tag in version_tags:
        return None
    if version_tags and _version_key(pending_tag) <= _version_key(version_tags[-1]):
        return None
    return pending_tag


def group_by_release(repo: Path, changes: list[tuple[Path, dict]]) -> dict[str, list[dict]]:
    version_tags = sorted((t for t in _git_strict(repo, "tag", "--list", "v*").splitlines() if t.strip()),
                           key=_version_key)
    pending_tag = _pending_release_tag(repo, version_tags)
    releases: dict[str, list[dict]] = {}
    added, exact = _added_commits(repo, [path for path, _ in changes])
    release_of = _release_map(repo, {c for c, _ in added.values()}, version_tags)
    for path, entry in changes:
        override = entry.get("release")
        if path in exact:
            commit = _added_commit(repo, path)
            landed = _landed_at(repo, commit) if commit else None
            own_release = _release_for(repo, commit, version_tags) if commit else "Unreleased"
        else:
            commit, ct = added.get(path, (None, None))
            landed = datetime.fromtimestamp(ct, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ct is not None else None
            own_release = release_of.get(commit, "Unreleased") if commit else "Unreleased"
        if landed is not None:
            entry["landed_at"] = landed
        if isinstance(override, str) and override.strip():
            release = override.strip()
        else:
            release = own_release
            if release == "Unreleased" and pending_tag is not None:
                release = pending_tag
        releases.setdefault(release, []).append(entry)
    return releases


def build_index(
    areas: list[dict],
    catalog: dict[str, dict],
    changes: list[tuple[Path, dict]],
    releases: dict[str, list[dict]] | None = None,
) -> dict:
    if releases is not None:
        for release_name, entries in releases.items():
            for entry in entries:
                entry["release"] = release_name
    return {
        "areas": areas,
        "catalog": sorted(catalog.values(), key=lambda e: e["id"]),
        "changes": sorted((entry for _, entry in changes), key=lambda c: (c["date"], c["summary"])),
    }


def render_markdown(areas: list[dict], catalog: dict[str, dict], releases: dict[str, list[dict]]) -> str:
    lines = ["# Features", "", "Generated by `scripts/features.py render`. Do not hand-edit.", "",
              "## Catalog"]
    for area in areas:
        entries = sorted(
            (e for e in catalog.values() if e.get("area") == area["id"] and e.get("status") != "removed"),
            key=lambda e: e["id"],
        )
        if not entries:
            continue
        lines += ["", f"### {area['name']}", "", area.get("blurb", "")]
        for e in entries:
            badge = "" if e["status"] == "stable" else f" ({e['status']})"
            lines += ["", f"#### {e['name']}{badge}", "", e["summary"]]
            if e.get("description"):
                lines += ["", e["description"]]

    lines += ["", "## Update log", ""]
    names = sorted((n for n in releases if n != "Unreleased"), key=_version_key, reverse=True)
    ordered = (["Unreleased"] if "Unreleased" in releases else []) + names
    for name in ordered:
        visible = [c for c in releases[name] if c.get("type") != "internal"]
        lines.append(f"### {name}")
        if not visible:
            lines += ["", "_internal only_", ""]
            continue
        lines.append("")
        for c in sorted(visible, key=lambda c: (c["date"], c["summary"])):
            lines.append(f"- **{c['type']}**: {c['summary']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_render(args: argparse.Namespace) -> int:
    if _git(REPO, "rev-parse", "--is-inside-work-tree").returncode != 0:
        print("features.py render: CANNOT DETERMINE - not inside a git checkout", file=sys.stderr)
        return 2
    areas, catalog, changes, errors = _load_all()
    if errors:
        for e in errors:
            print(f"features.py render: {e}", file=sys.stderr)
        print(f"features.py render: {len(errors)} violation(s), nothing written", file=sys.stderr)
        return 1
    try:
        releases = group_by_release(REPO, changes)
    except RuntimeError as exc:
        print(f"features.py render: CANNOT DETERMINE - {exc}", file=sys.stderr)
        return 2
    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(SCHEMA_FILE, build_schema())
    _write_json(INDEX_FILE, build_index(areas, catalog, changes, releases))
    FEATURES_MD.write_text(render_markdown(areas, catalog, releases), encoding="utf-8")
    print(f"features.py render: wrote {FEATURES_MD.relative_to(REPO)}, "
          f"{INDEX_FILE.relative_to(REPO)}, {SCHEMA_FILE.relative_to(REPO)}")
    return 0


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40].rstrip("-") or "change"


def cmd_new_change(args: argparse.Namespace) -> int:
    date_str = args.date or date.today().isoformat()
    if not DATE_RX.match(date_str):
        print(f"features.py new-change: --date must be YYYY-MM-DD, got {date_str!r}", file=sys.stderr)
        return 1
    features = [f.strip() for f in args.features.split(",") if f.strip()]
    entry: dict[str, Any] = {
        "date": date_str,
        "type": args.type,
        "features": features,
        "summary": args.summary,
    }
    if args.details:
        entry["details"] = args.details
    if args.issue is not None:
        entry["issue"] = args.issue
    entry["pr"] = args.pr
    if args.breaking:
        entry["breaking"] = True

    errors = validate_record(entry, CHANGE_FIELDS, "new-change")
    if not features and args.type != "internal":
        errors.append("new-change: --features is required unless --type internal")
    if errors:
        for e in errors:
            print(f"features.py {e}", file=sys.stderr)
        return 1

    slug = args.slug or _slugify(args.summary)
    if args.slug and not re.match(r"^[a-z0-9][a-z0-9-]*$", args.slug):
        print(f"features.py new-change: --slug must be lowercase kebab-case, got {args.slug!r}",
              file=sys.stderr)
        return 1
    CHANGES_DIR.mkdir(parents=True, exist_ok=True)
    path = CHANGES_DIR / f"{date_str}-{args.pr}-{slug}.json"
    if path.exists():
        print(f"features.py new-change: {path.relative_to(REPO)} already exists", file=sys.stderr)
        return 1
    _write_json(path, entry)
    print(f"features.py new-change: wrote {path.relative_to(REPO)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="features.py", description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check_p = sub.add_parser("check", help="validate features/ (0 pass, 1 violation, 2 could not determine)")
    check_p.add_argument("--branch", action="store_true",
                          help="also enforce the per-PR change-file and updated-date rules")

    sub.add_parser("render", help="write FEATURES.md, features/index.json, features/schema.json")

    new_p = sub.add_parser("new-change", help="write one features/changes/ entry")
    new_p.add_argument("--type", required=True, choices=CHANGE_TYPES)
    new_p.add_argument("--features", default="", help="comma-separated catalog ids; required unless internal")
    new_p.add_argument("--summary", required=True, help="one user-facing line")
    new_p.add_argument("--details", help="optional markdown detail")
    new_p.add_argument("--issue", type=int, help="issue number")
    new_p.add_argument("--pr", type=int, required=True, help="PR number, known at claim time")
    new_p.add_argument("--breaking", action="store_true")
    new_p.add_argument("--date", help="YYYY-MM-DD, default today")
    new_p.add_argument("--slug", help="override the auto-slug from --summary")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return cmd_check(args)
    if args.command == "render":
        return cmd_render(args)
    return cmd_new_change(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
