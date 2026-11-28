
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException

from src.core.catalog import publish_prepare_kinds
from src.core.catalog.submission_rules import RESERVED_SKILL_NAMES, SKILL_NAME_RE
from src.plugins.host.sideload import SideloadRefused
from src.plugins.host.sideload_git import check_subdir, parse_github_source
from src.plugins.sdk.cplug_validate import SEMVER as VERSION_RE

_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_V_TAG_PREFIX = re.compile(r"^[vV](?=\d)")


@dataclass(frozen=True)
class PreparedGitHubPublish:

    owner: str
    repo: str
    repo_slug: str
    tag: str
    pointer: str
    commit_sha: str
    subdir: str
    kind: str
    name: str
    version: str
    digest: str
    location_id: str


def _fail(status_code: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "detail": detail})


def prepare_github_publish(
    *,
    pointer: Optional[str] = None,
    repo: Optional[str] = None,
    tag: Optional[str] = None,
    commit_sha: Optional[str] = None,
    subdir: Optional[str] = None,
    kind: Optional[str] = None,
    name: Optional[str] = None,
    version: Optional[str] = None,
    default_kind: str = publish_prepare_kinds.KIND_CPLUG,
) -> PreparedGitHubPublish:
    raw_source: Optional[str] = None
    explicit_ref: Optional[str] = tag
    if pointer:
        raw_source = pointer
    elif repo:
        raw_source = repo
    else:
        raise _fail(422, "source_missing", "provide a GitHub pointer (owner/repo@tag) or repo + tag")

    if raw_source.startswith(("git@", "ssh://", "http://")):
        raise _fail(422, "git_url_refused", "only owner/repo@tag or https://github.com/owner/repo@tag is allowed")

    if pointer and repo:
        try:
            p_owner, p_repo, _u, _r = parse_github_source(pointer)
            r_owner, r_repo, _u2, r_ref = parse_github_source(repo)
        except SideloadRefused as exc:
            raise _fail(exc.status, exc.code, str(exc)) from exc
        if r_ref is not None or (p_owner, p_repo) != (r_owner, r_repo):
            raise _fail(422, "git_url_refused", "pointer and repo must refer to the same owner/repo")

    try:
        owner, repo_name, _canon, parsed_tag = parse_github_source(raw_source, ref=explicit_ref)
    except SideloadRefused as exc:
        raise _fail(exc.status, exc.code, str(exc)) from exc

    if not parsed_tag:
        raise _fail(422, "ref_invalid", "Warez GitHub publish requires an explicit @tag (owner/repo@tag)")

    clean_sha = (commit_sha or "").strip()
    if clean_sha and not _COMMIT_SHA_RE.match(clean_sha):
        raise _fail(422, "commit_sha_invalid", "commit_sha must be 40 lowercase hexadecimal characters")

    try:
        parts = check_subdir(subdir)
    except SideloadRefused as exc:
        raise _fail(exc.status, exc.code, str(exc)) from exc
    clean_subdir = "/".join(parts)

    eff_kind = (kind or default_kind).strip()
    if eff_kind not in ("cplug", "skill", "theme", "plugin", "mod"):
        raise _fail(422, "kind_not_supported", f"unsupported publish kind {eff_kind!r}")

    eff_name = (name or repo_name).strip()
    if eff_kind == "cplug":
        if not publish_prepare_kinds.CPLUG_ID_PATTERN.match(eff_name):
            raise _fail(
                422,
                "name_invalid",
                f"plugin id {eff_name!r} must match {publish_prepare_kinds.CPLUG_ID_PATTERN.pattern}",
            )
        if eff_name in publish_prepare_kinds.CPLUG_RESERVED_IDS:
            raise _fail(409, "name_reserved", f"plugin id {eff_name!r} is reserved")
    else:
        if not SKILL_NAME_RE.match(eff_name):
            raise _fail(422, "name_invalid", f"invalid item name {eff_name!r}")
        if eff_kind == "skill" and eff_name.lower() in RESERVED_SKILL_NAMES:
            raise _fail(409, "name_reserved", f"skill name {eff_name!r} is reserved")

    eff_version = (version or _V_TAG_PREFIX.sub("", parsed_tag, count=1)).strip()
    if not VERSION_RE.match(eff_version):
        raise _fail(422, "version_invalid", f"version {eff_version!r} must be semver (major.minor.patch)")

    repo_slug = f"{owner}/{repo_name}"
    canon_pointer = f"{repo_slug}@{parsed_tag}"
    payload = "\0".join(
        ("github-pointer-v1", canon_pointer, eff_kind, eff_name, eff_version, clean_sha, clean_subdir)
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return PreparedGitHubPublish(
        owner=owner,
        repo=repo_name,
        repo_slug=repo_slug,
        tag=parsed_tag,
        pointer=canon_pointer,
        commit_sha=clean_sha,
        subdir=clean_subdir,
        kind=eff_kind,
        name=eff_name,
        version=eff_version,
        digest=digest,
        location_id=f"github:{canon_pointer}",
    )


def build_hosted_github_payload(
    prepared: PreparedGitHubPublish,
    *,
    files: Optional[list[dict[str, Any]]] = None,
    is_v2: bool = False,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "source_type": "github",
        "pointer": prepared.pointer,
        "repo": prepared.repo_slug,
        "tag": prepared.tag,
        "kind": prepared.kind,
        "name": prepared.name,
        "version": prepared.version,
    }
    if prepared.commit_sha:
        body["commit_sha"] = prepared.commit_sha
    if prepared.subdir:
        body["subdir"] = prepared.subdir
    if files is not None:
        body["files"] = files
    if is_v2:
        body["schema"] = 2
    return body
