
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.plugins.cli import checker, tester
from src.plugins.cli.auth_discovery import CliAuthError, CliHttpClient
from src.plugins.host.sideload import SideloadRefused
from src.plugins.host.sideload_git import parse_github_source

_GITHUB_URL_RE = re.compile(r"^(https://github\.com/|git@github\.com:)", re.IGNORECASE)


class CliPublishTargetError(ValueError):
    pass


def parse_publish_target(
    target: Optional[str] = None,
    *,
    github: Optional[str] = None,
    tag: Optional[str] = None,
) -> Tuple[str, Dict[str, Any]]:
    raw = (target or "").strip()
    if github:
        owner, repo, _canon, parsed_tag = parse_github_source(github, ref=tag)
        if not parsed_tag:
            raise CliPublishTargetError("GitHub publish requires an explicit @tag (owner/repo@tag or --tag)")
        repo_slug = f"{owner}/{repo}"
        spec: Dict[str, Any] = {"pointer": f"{repo_slug}@{parsed_tag}", "repo": repo_slug, "tag": parsed_tag}
        if raw and Path(raw).expanduser().exists():
            spec["path"] = Path(raw).expanduser().resolve()
        return "github", spec
    if not raw:
        return "local", {"path": Path(".").resolve()}
    p = Path(raw).expanduser()
    if p.exists() or raw.startswith((".", "/", "~")):
        return "local", {"path": p.resolve()}
    if _GITHUB_URL_RE.match(raw) or "@" in raw or "/" in raw:
        owner, repo, _canon, parsed_tag = parse_github_source(raw, ref=tag)
        if not parsed_tag:
            raise CliPublishTargetError("GitHub publish requires an explicit @tag (owner/repo@tag or --tag)")
        repo_slug = f"{owner}/{repo}"
        return "github", {"pointer": f"{repo_slug}@{parsed_tag}", "repo": repo_slug, "tag": parsed_tag}
    return "local", {"path": p.resolve()}


def detect_source(source: str, *, mode: str = "auto") -> Tuple[str, Dict[str, Any]]:
    if mode in ("local", "github", "warez"):
        kind = mode
    else:
        p = Path(source)
        if p.exists() or source.startswith((".", "/", "~")):
            kind = "local"
        elif _GITHUB_URL_RE.match(source) or source.endswith(".git") or "@" in source:
            kind = "github"
        elif "/" in source:
            kind = "warez"
        else:
            kind = "warez"

    if kind == "local":
        return "local", {"path": str(Path(source).expanduser().resolve())}
    if kind == "github":
        raw = source.strip()
        ref: Optional[str] = None
        if not _GITHUB_URL_RE.match(raw):
            repo_part, _, ref_part = raw.partition("@")
            url = f"https://github.com/{repo_part.strip('/')}.git"
            ref = ref_part or None
        else:
            url = raw
        return "github", {"url": url, **({"ref": ref} if ref else {})}
    return "warez", {"item_id": source.strip()}


def _confirm(prompt: str, *, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    sys.stdout.write(f"{prompt} [y/N]: ")
    sys.stdout.flush()
    ans = sys.stdin.readline().strip().lower()
    return ans in ("y", "yes")


def run_install(
    source: str,
    *,
    client: Optional[CliHttpClient] = None,
    mode: str = "auto",
    assume_yes: bool = False,
    enable: bool = True,
    as_json: bool = False,
) -> int:
    kind, spec = detect_source(source, mode=mode)
    if client is None:
        client = CliHttpClient()
    try:
        if kind == "local":
            sc, res = client.request("POST", "/api/v1/cplug-owner/sideload", json_body={"path": spec["path"]})
        elif kind == "github":
            if not _confirm(f"Install unverified GitHub repository {spec['url']} behind OS sandbox?", assume_yes=assume_yes):
                sys.stderr.write("install aborted by user\n")
                return 2
            sc, res = client.request("POST", "/api/v1/cplug-owner/sideload/git", json_body=spec)
        else:
            sc, preview = client.request(
                "POST",
                "/api/v1/catalog/install/preview",
                json_body={"item_id": spec["item_id"], "scope": "global"},
            )
            if sc >= 400:
                sys.stderr.write(f"preview failed ({sc}): {preview}\n")
                return 1
            flagged = bool(preview.get("requires_warning_ack") or preview.get("flagged"))
            if flagged:
                reasons = preview.get("warning_reasons") or []
                review = preview.get("review") if isinstance(preview.get("review"), dict) else {}
                summary = review.get("summary") or preview.get("ai_summary") or ""
                if reasons:
                    sys.stderr.write(f"warning: {spec['item_id']} is flagged ({'; '.join(str(r) for r in reasons)})\n")
                if summary:
                    sys.stderr.write(f"review summary: {summary}\n")
                if not _confirm(f"Proceed installing flagged item {spec['item_id']}?", assume_yes=assume_yes):
                    sys.stderr.write("install aborted by user\n")
                    return 2
            elif not _confirm(f"Install Warez item {spec['item_id']}?", assume_yes=assume_yes):
                sys.stderr.write("install aborted by user\n")
                return 2
            install_body: Dict[str, Any] = {
                "item_id": spec["item_id"],
                "scope": "global",
                "plan_token": preview.get("plan_token"),
            }
            needs_consent = bool(
                preview.get("requires_consent")
                or preview.get("cplug_facts_sha")
                or preview.get("script_files")
                or preview.get("mod_report_sha")
                or flagged
            )
            if needs_consent:
                digest = preview.get("digest")
                body_sha = preview.get("body_sha")
                if not isinstance(digest, str) or not digest or not isinstance(body_sha, str) or not body_sha:
                    sys.stderr.write("preview response missing digest/body_sha required for consent\n")
                    return 1
                consent: Dict[str, Any] = {
                    "digest": digest,
                    "body_sha": body_sha,
                    "scripts": True,
                }
                if preview.get("cplug_facts_sha"):
                    consent["cplug_accepted"] = True
                    consent["cplug_facts_sha"] = preview["cplug_facts_sha"]
                if flagged:
                    consent["cplug_flagged_ack"] = True
                if preview.get("mod_report_sha"):
                    consent["mod_trust"] = True
                    consent["mod_report_sha"] = preview["mod_report_sha"]
                    if preview.get("mod_flagged_ack_needed"):
                        consent["mod_flagged_ack"] = True
                install_body["consent"] = consent
            sc, res = client.request("POST", "/api/v1/catalog/install", json_body=install_body)
    except CliAuthError as exc:
        sys.stderr.write(f"install auth failed: {exc}\n")
        return 2

    if sc >= 400:
        sys.stderr.write(f"install failed ({sc}): {res}\n")
        return 1

    plugin_id = (res.get("id") or res.get("name")) if isinstance(res, dict) else None
    item_kind = res.get("kind") if isinstance(res, dict) else None
    if enable and isinstance(plugin_id, str) and plugin_id and item_kind in (None, "cplug"):
        rc, row = client.request("GET", f"/api/v1/cplugs/{plugin_id}")
        if rc >= 400:
            sys.stderr.write(f"enable lookup failed ({rc}): {row}\n")
            return 1
        if isinstance(row, dict) and (not row.get("enabled") or row.get("state") == "needs_approval"):
            sc2, sheet = client.request("GET", f"/api/v1/cplugs/{plugin_id}/sheet")
            if sc2 >= 400 or not isinstance(sheet, dict):
                sys.stderr.write(f"enable sheet failed ({sc2}): {sheet}\n")
                return 1
            perms = row.get("permissions", {}).get("app", [])
            ticks = [
                p["name"]
                for p in sheet.get("permissions", [])
                if isinstance(p, dict) and (p.get("needs_tick") or p.get("risk") in ("medium", "high"))
            ]
            ui_slot_rows = [
                s
                for s in sheet.get("ui_slots", [])
                if isinstance(s, dict) and isinstance(s.get("slot"), str)
            ]
            ui_slots = [s["slot"] for s in ui_slot_rows]
            slot_ticks = [
                s["slot"]
                for s in ui_slot_rows
                if s.get("needs_tick") or s.get("risk") in ("medium", "high")
            ]
            if ui_slot_rows:
                slot_desc = ", ".join(
                    f"{s['slot']} ({s['reason']})" if s.get("reason") else s["slot"]
                    for s in ui_slot_rows
                )
                sys.stderr.write(f"ui slots for {plugin_id}: {slot_desc}\n")
                if slot_ticks and not _confirm(
                    f"Grant UI slot contributions ({', '.join(ui_slots)}) for {plugin_id}?",
                    assume_yes=assume_yes,
                ):
                    sys.stderr.write("enable aborted by user\n")
                    return 2
            grants_body: Dict[str, Any] = {"app": perms}
            consent_body: Dict[str, Any] = {
                "digest": sheet.get("digest", ""),
                "body_sha": sheet.get("body_sha", ""),
                "grants_sha": sheet.get("grants_sha", ""),
                "ticks": ticks,
            }
            if ui_slot_rows or row.get("grants", {}).get("ui_slots"):
                grants_body["ui_slots"] = ui_slots
                consent_body["ui_slots_sha"] = sheet.get("ui_slots_sha", "")
                consent_body["slot_ticks"] = slot_ticks
            put_body: Dict[str, Any] = {
                "revision": row.get("revision", 0),
                "enabled": True,
                "grants": grants_body,
                "consent": consent_body,
            }
            rc_put, put_res = client.request("PUT", f"/api/v1/cplugs/{plugin_id}", json_body=put_body)
            if rc_put >= 400:
                sys.stderr.write(f"enable failed ({rc_put}): {put_res}\n")
                return 1

    if as_json:
        sys.stdout.write(json.dumps(res, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(f"installed {plugin_id or source}\n")
    return 0


def run_publish(
    target: Path | str,
    *,
    version: Optional[str] = None,
    github: Optional[str] = None,
    tag: Optional[str] = None,
    commit_sha: Optional[str] = None,
    subdir: Optional[str] = None,
    kind: Optional[str] = None,
    name: Optional[str] = None,
    client: Optional[CliHttpClient] = None,
    assume_yes: bool = False,
    as_json: bool = False,
) -> int:
    try:
        mode, spec = parse_publish_target(
            str(target) if target is not None else None,
            github=github,
            tag=tag,
        )
    except (SideloadRefused, CliPublishTargetError) as exc:
        sys.stderr.write(f"publish target error: {exc}\n")
        return 1

    folder: Optional[Path] = spec.get("path")
    if mode == "local":
        assert folder is not None
        chk = checker.check_folder(folder)
        if not chk.ok:
            for err in chk.errors:
                sys.stderr.write(f"check error: {err}\n")
            return 1
        tst = tester.test_folder(folder)
        if not tst.ok:
            for err in tst.errors:
                sys.stderr.write(f"test error: {err}\n")
            return 1
        assert chk.manifest_v2 is not None
        ver = version or chk.manifest_v2.version
    elif folder is not None:
        chk = checker.check_folder(folder)
        if not chk.ok:
            for err in chk.errors:
                sys.stderr.write(f"check error: {err}\n")
            return 1
        tst = tester.test_folder(folder)
        if not tst.ok:
            for err in tst.errors:
                sys.stderr.write(f"test error: {err}\n")
            return 1
        assert chk.manifest_v2 is not None
        ver = version or chk.manifest_v2.version
    else:
        ver = version

    if client is None:
        client = CliHttpClient()
    try:
        sc_acct, acct = client.request("GET", "/api/v1/catalog/handle")
        if sc_acct >= 400:
            sys.stderr.write(f"publish account lookup failed ({sc_acct}): {acct}\n")
            return 1
        handle = str((acct or {}).get("handle") or "")
        if not handle:
            sys.stderr.write("publish requires a claimed publisher handle in Carnivore\n")
            return 2

        base_body: Dict[str, Any] = {}
        if folder is not None:
            base_body["path"] = str(folder)
        if mode == "github":
            base_body.update({
                "source_type": "github",
                "pointer": spec["pointer"],
                "repo": spec["repo"],
                "tag": spec["tag"],
            })
            if commit_sha:
                base_body["commit_sha"] = commit_sha
            if subdir:
                base_body["subdir"] = subdir
            if kind:
                base_body["kind"] = kind
            if name:
                base_body["name"] = name
        if ver:
            base_body["version"] = ver

        sc_prev, prev = client.request(
            "POST",
            "/api/v1/cplug-owner/publish",
            json_body={**base_body, "dry_run": True},
        )
        if sc_prev >= 400 or not isinstance(prev, dict):
            sys.stderr.write(f"publish preview failed ({sc_prev}): {prev}\n")
            return 1
        if not prev.get("can_send"):
            for ref in prev.get("refusals", []):
                if isinstance(ref, dict):
                    sys.stderr.write(f"refusal: {ref.get('code')}: {ref.get('detail')}\n")
            return 1

        prompt = (
            f"Publish {handle}/{prev['name']}@{prev['version']} from {spec['pointer']}?"
            if mode == "github" and folder is None
            else f"Publish {handle}/{prev['name']}@{prev['version']} ({prev['file_count']} files)?"
        )
        if not _confirm(prompt, assume_yes=assume_yes):
            sys.stderr.write("publish aborted by user\n")
            return 2

        sc, res = client.request(
            "POST",
            "/api/v1/cplug-owner/publish",
            json_body={
                **base_body,
                "version": prev["version"],
                "digest": prev["digest"],
                "dry_run": False,
            },
        )
    except CliAuthError as exc:
        sys.stderr.write(f"publish auth failed: {exc}\n")
        return 2

    if sc >= 400:
        sys.stderr.write(f"publish failed ({sc}): {res}\n")
        return 1
    if as_json:
        sys.stdout.write(json.dumps(res, separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(f"published submission: {res}\n")
    return 0
