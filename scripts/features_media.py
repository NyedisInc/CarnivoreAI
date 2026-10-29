
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SIZE_CAPS = {".png": 400 * 1024, ".webp": 400 * 1024, ".gif": 2 * 1024 * 1024, ".svg": 50 * 1024}
KIND_EXTS = {"screenshot": {".png", ".webp"}, "gif": {".gif"}, "icon": {".png", ".svg", ".webp"}}
CAPTURED_EXTS = {".png", ".webp", ".gif"}
SHOWN_TYPES = ("added", "changed")

STEP_OPS: dict[str, type | tuple[type, ...]] = {
    "goto": str,
    "click": str,
    "dblclick": str,
    "hover": str,
    "press": str,
    "type": str,
    "wait_for": str,
    "wait": int,
    "set_theme": str,
    "set_viewport": dict,
    "drag": dict,
    "api": dict,
    "scroll": dict,
}
SHOT_KINDS = ("screenshot", "gif", "icon")
SHOT_KEYS = {"name", "kind", "steps", "record", "target", "clip", "pad", "hide"}
SPEC_KEYS = {"feature", "viewport", "theme", "scale", "seed", "mocks", "shots", "drawer_width", "unpaired"}
SEED_KEYS = {"sessions", "preferences", "config", "transcripts"}


def fix_command(fid: str) -> str:
    return f"python3 scripts/feature_capture.py {fid}"


def _looks_like_path(value: str) -> bool:
    return "/" in value and " " not in value and not value.startswith("/")


def validate_steps(steps: Any, where: str) -> list[str]:
    if not isinstance(steps, list):
        return [f"{where}: must be a list of steps"]
    errors = []
    for i, step in enumerate(steps):
        at = f"{where}[{i}]"
        if not isinstance(step, dict) or len(step) != 1:
            errors.append(f"{at}: a step is an object with exactly one operation")
            continue
        op, arg = next(iter(step.items()))
        if op not in STEP_OPS:
            errors.append(f"{at}: unknown step {op!r} (known: {', '.join(sorted(STEP_OPS))})")
        elif not isinstance(arg, STEP_OPS[op]) or isinstance(arg, bool):
            errors.append(f"{at}: step {op!r} takes a {STEP_OPS[op].__name__}")
        elif op == "goto" and not arg.startswith("/"):
            errors.append(f"{at}: goto takes a path on the leased server, starting with '/'")
        elif op == "api" and not str(arg.get("path", "")).startswith("/api/"):
            errors.append(f"{at}: api path must start with /api/")
    return errors


def validate_capture_spec(spec: Any, fid: str, where: str) -> tuple[list[str], set[str]]:
    if not isinstance(spec, dict):
        return [f"{where}: must be a JSON object"], set()
    errors = [f"{where}: unknown key {k!r}" for k in sorted(set(spec) - SPEC_KEYS)]
    if spec.get("feature") != fid:
        errors.append(f"{where}: 'feature' must be {fid!r}, the file's own name")
    vp = spec.get("viewport")
    if vp is not None and not (isinstance(vp, dict) and all(isinstance(vp.get(k), int) for k in ("width", "height"))):
        errors.append(f"{where}: 'viewport' must be {{\"width\": int, \"height\": int}}")
    dw = spec.get("drawer_width")
    if dw is not None and not (isinstance(dw, int) and not isinstance(dw, bool) and 240 <= dw <= 480):
        errors.append(f"{where}: 'drawer_width' must be an int from 240 to 480")
    unpaired = spec.get("unpaired", False)
    if not isinstance(unpaired, bool):
        errors.append(f"{where}: 'unpaired' must be true or false")
    elif unpaired and spec.get("seed"):
        errors.append(f"{where}: an 'unpaired' spec has no sign-in, so it cannot carry a 'seed' (mocks are fine)")
    seed = spec.get("seed", {})
    if not isinstance(seed, dict) or set(seed) - SEED_KEYS:
        errors.append(f"{where}: 'seed' may only carry {sorted(SEED_KEYS)}")
    mocks = spec.get("mocks", [])
    if not isinstance(mocks, list) or not all(
            isinstance(m, dict) and isinstance(m.get("url"), str) and "/api/" in m["url"]
            and ("json" in m) != ("json_file" in m) and set(m) <= {"url", "json", "json_file"} for m in mocks):
        errors.append(f"{where}: 'mocks' must be a list of {{\"url\": \"**/api/...\", \"json\": ...}} "
                      "or {\"url\": ..., \"json_file\": \"fixtures/<name>.json\"}")
    errors += [f"{where}: mock json_file {m['json_file']!r} must be fixtures/<name>.json"
               for m in mocks if isinstance(m, dict) and isinstance(m.get("json_file"), str)
               and not re.fullmatch(r"fixtures/[\w.-]+\.json", m["json_file"])]
    shots = spec.get("shots")
    produced: set[str] = set()
    if not isinstance(shots, list) or not shots:
        return errors + [f"{where}: 'shots' must be a non-empty list"], produced
    for i, shot in enumerate(shots):
        at = f"{where}: shots[{i}]"
        if not isinstance(shot, dict):
            errors.append(f"{at}: must be an object")
            continue
        errors += [f"{at}: unknown key {k!r}" for k in sorted(set(shot) - SHOT_KEYS)]
        name, kind = shot.get("name"), shot.get("kind")
        if not isinstance(name, str) or not name or "/" in name or ".." in name:
            errors.append(f"{at}: 'name' must be a plain file stem")
            continue
        if kind not in SHOT_KINDS:
            errors.append(f"{at}: 'kind' must be one of {SHOT_KINDS}")
            continue
        errors += validate_steps(shot.get("steps", []), f"{at}.steps")
        if kind == "gif":
            if not shot.get("record"):
                errors.append(f"{at}: a gif needs a non-empty 'record' step list")
            errors += validate_steps(shot.get("record", []), f"{at}.record")
        elif "record" in shot:
            errors.append(f"{at}: only a gif takes 'record'")
        clip = shot.get("clip")
        if clip is not None and not (isinstance(clip, dict) and all(
                isinstance(clip.get(k), int) for k in ("x", "y", "width", "height"))):
            errors.append(f"{at}: 'clip' must be {{\"x\", \"y\", \"width\", \"height\"}} integers")
        if clip is not None and shot.get("target"):
            errors.append(f"{at}: use 'target' or 'clip', not both")
        file = f"{name}.{'gif' if kind == 'gif' else 'png'}"
        if file in produced:
            errors.append(f"{at}: two shots produce {file!r}")
        produced.add(file)
    return errors, produced


def _media_item_errors(fid: str, item: dict, folder: Path, where: str) -> list[str]:
    file = item.get("file")
    if not isinstance(file, str):
        return []
    if ".." in file or "/" in file or "\\" in file:
        return [f"{where}: file {file!r} must be a plain name inside features/media/{fid}/ (no '..' or '/')"]
    path = folder / file
    ext = path.suffix.lower()
    errors = []
    kind = item.get("kind")
    if kind in KIND_EXTS and ext not in KIND_EXTS[kind]:
        errors.append(f"{where}: a {kind} must be {sorted(KIND_EXTS[kind])}, got {file!r}")
    if path.is_symlink() or (path.exists() and folder.resolve() not in path.resolve().parents):
        return errors + [f"{where}: {file!r} resolves outside features/media/{fid}/"]
    if not path.is_file():
        hint = f"; run: {fix_command(fid)}" if ext in CAPTURED_EXTS else ""
        return errors + [f"{where}: media file features/media/{fid}/{file} does not exist{hint}"]
    cap = SIZE_CAPS.get(ext)
    size = path.stat().st_size
    if cap and size > cap:
        errors.append(f"{where}: features/media/{fid}/{file} is {size} bytes, over the {cap}-byte cap for {ext}")
    return errors


def validate_media(features_dir: Path, catalog: dict[str, dict], repo: Path) -> list[str]:
    media_root, capture_root = features_dir / "media", features_dir / "capture"
    errors: list[str] = []
    produced_by: dict[str, set[str]] = {}
    if capture_root.is_dir():
        for path in sorted(capture_root.glob("*.json")):
            where = path.relative_to(repo).as_posix()
            if path.stem not in catalog:
                errors.append(f"{where}: no catalog entry features/catalog/{path.stem}.json")
                continue
            try:
                spec = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{where}: {exc}")
                continue
            spec_errors, produced = validate_capture_spec(spec, path.stem, where)
            errors += spec_errors
            produced_by[path.stem] = produced

    for fid, entry in sorted(catalog.items()):
        media = entry.get("media")
        where = f"features/catalog/{fid}.json"
        if media and entry.get("media_exempt"):
            errors.append(f"{where}: carries both 'media' and 'media_exempt'; pick one")
        folder = media_root / fid
        listed = set()
        for i, item in enumerate(media if isinstance(media, list) else []):
            if not isinstance(item, dict):
                continue
            errors += _media_item_errors(fid, item, folder, f"{where}: media[{i}]")
            file = item.get("file")
            if isinstance(file, str):
                listed.add(file)
                if Path(file).suffix.lower() in CAPTURED_EXTS and file not in produced_by.get(fid, set()):
                    errors.append(f"{where}: media[{i}] {file!r} is not produced by any shot in "
                                  f"features/capture/{fid}.json, so it cannot be regenerated")
        if folder.is_dir():
            for stray in sorted(p.name for p in folder.iterdir() if p.name not in listed):
                errors.append(f"features/media/{fid}/{stray}: not listed in {where} 'media' "
                              "(add it with alt text, or delete it)")

    if media_root.is_dir():
        for folder in sorted(p for p in media_root.iterdir() if p.is_dir() and p.name not in catalog):
            errors.append(f"features/media/{folder.name}/: no catalog entry features/catalog/{folder.name}.json")
    return errors


def branch_change_entries(repo: Path, paths: list[str]) -> list[tuple[str, dict]]:
    found = []
    for p in paths:
        if p.startswith("features/changes/") and p.endswith(".json") and (repo / p).is_file():
            try:
                data = json.loads((repo / p).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict):
                found.append((p, data))
    return found


def check_branch_media(repo: Path, paths: list[str], catalog: dict[str, dict]) -> list[str]:
    errors: list[str] = []
    touched_media = {p.split("/")[2] for p in paths if p.startswith("features/media/") and p.count("/") >= 3}
    for change_path, change in branch_change_entries(repo, paths):
        if change.get("type") not in SHOWN_TYPES:
            continue
        for fid in change.get("features") or []:
            entry = catalog.get(fid)
            if entry is None:
                continue
            missing = [f for f in ("where", "how_to", "examples") if not entry.get(f)]
            exempt = bool(entry.get("media_exempt"))
            if not entry.get("media") and not exempt:
                missing.append("media (or media_exempt: \"<reason>\")")
            if missing:
                errors.append(f"{change_path} ({change['type']}) names feature {fid!r}, whose "
                              f"features/catalog/{fid}.json is missing: {', '.join(missing)}. "
                              f"Write the text, add a features/capture/{fid}.json spec, then run: "
                              f"{fix_command(fid)}")
            if exempt or change.get("media_unchanged") is True:
                continue
            surfaces = [s for s in entry.get("surfaces", []) if isinstance(s, str) and _looks_like_path(s)]
            hit = [p for p in paths if any(p == s or p.startswith(s.rstrip("/") + "/") for s in surfaces)]
            if hit and fid not in touched_media:
                errors.append(f"{change_path} ({change['type']}): this branch changes {hit[0]}, a surface "
                              f"of feature {fid!r}, but nothing under features/media/{fid}/ changed. "
                              f"Recapture it: {fix_command(fid)} (if the capture comes out identical, "
                              "the visuals did not change: set \"media_unchanged\": true on the change entry)")
    return errors
