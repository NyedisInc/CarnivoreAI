from __future__ import annotations

import base64
import hashlib
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "macOS" / "scripts" / "publish-update-assets.sh"
SECRET = "ghp_SENTINEL_TOKEN_VALUE"
WRITES = ("release create", "release upload", "release edit", "release delete-asset")

FAKE_GH = r"""#!/usr/bin/env bash
# Fake gh: log argv, answer the few read calls the script makes from FAKE_* env.
printf '%s\n' "$*" >> "$FAKE_GH_LOG"
case "$1 $2" in
  "api user") echo "${FAKE_LOGIN:-NyedisAdam}"; exit 0 ;;
esac
if [[ "$1" == "api" && "$2" == repos/*/git/ref/tags/* ]]; then
  [[ "${FAKE_TAG_EXISTS:-1}" == 1 ]] && exit 0 || exit 1
fi
if [[ "$1 $2" == "release view" ]]; then
  case "$*" in
    *assets*) printf '%b' "${FAKE_ASSETS:-}"; exit 0 ;;
    *) for t in ${FAKE_RELEASES:-}; do [[ "$t" == "$3" ]] && { echo "${FAKE_DRAFT:-false}"; exit 0; }; done; exit 1 ;;
  esac
fi
exit 0
"""


def make_dist(tmp_path: Path, version: str, zip_name: str) -> Path:
    dist = tmp_path / "dist"
    dist.mkdir()
    data = b"zip-bytes-" + version.encode()
    (dist / zip_name).write_bytes(data)
    (dist / (zip_name + ".blockmap")).write_bytes(b"map")
    sha = base64.b64encode(hashlib.sha512(data).digest()).decode()
    (dist / "latest-mac.yml").write_text(
        f"version: {version}\nfiles:\n  - url: {zip_name}\n    sha512: {sha}\n    size: {len(data)}\n"
        f"path: {zip_name}\nsha512: {sha}\n"
    )
    return dist


def run(tmp_path: Path, tag: str, *flags: str, zip_name: str = "Carnivore-1.16.3-arm64-mac.zip", **env: str):
    version = tag[1:]
    dist = make_dist(tmp_path, version, zip_name.replace("1.16.3", version))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    full_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "GH_TOKEN": SECRET,
        "FAKE_GH_LOG": str(log),
        **env,
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT), tag, str(dist), *flags], env=full_env, capture_output=True, text=True, timeout=60
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def writes(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith(WRITES)]


def index(calls: list[str], needle: str) -> int:
    for i, c in enumerate(calls):
        if needle in c:
            return i
    raise AssertionError(f"no call containing {needle!r} in {calls}")


def test_manifest_lands_last_and_stable_goes_draft_then_publish(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3")
    assert proc.returncode == 0, proc.stderr
    w = writes(calls)
    uploads = [c for c in w if c.startswith("release upload")]
    assert len(uploads) == 2
    assert "-mac.zip" in uploads[0] and "latest-mac.yml" not in uploads[0]
    assert "latest-mac.yml" in uploads[1] and ".zip" not in uploads[1]
    assert w[0].startswith("release create") and "--draft" in w[0]
    publish = [c for c in w if c.startswith("release edit")]
    assert len(publish) == 1 and "--draft=false" in publish[0] and "--latest" in publish[0]
    assert w.index(publish[0]) > w.index(uploads[1])


def test_published_release_is_not_redrafted(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3", FAKE_RELEASES="v1.16.3", FAKE_DRAFT="false")
    assert proc.returncode == 0, proc.stderr
    w = writes(calls)
    assert not any(c.startswith(("release create", "release edit")) for c in w)
    assert "-mac.zip" in w[0] and "latest-mac.yml" in w[1]


def test_beta_targets_channel_beta_and_never_latest(tmp_path):
    stale = "Carnivore-2.0.0-beta.1-mac.zip\\nlatest-mac.yml\\n"
    proc, calls = run(tmp_path, "v2.0.0-beta.2", "--channel", "beta", FAKE_ASSETS=stale)
    assert proc.returncode == 0, proc.stderr
    w = writes(calls)
    assert all("channel-beta" in c for c in w), w
    assert "v2.0.0-beta.2" not in " ".join(w)
    assert any(c.startswith("release create") and "--prerelease" in c and "--latest=false" in c for c in w)
    for c in w:
        assert "--latest" not in c.replace("--latest=false", ""), c
    manifest_at = max(i for i, c in enumerate(w) if c.startswith("release upload") and "latest-mac.yml" in c)
    deletes = [i for i, c in enumerate(w) if c.startswith("release delete-asset")]
    assert deletes and min(deletes) > manifest_at
    assert not any("beta.2" in w[i] for i in deletes)


def test_beta_edit_when_channel_exists_keeps_prerelease(tmp_path):
    proc, calls = run(tmp_path, "v2.0.0-beta.2", "--channel", "beta", FAKE_RELEASES="channel-beta")
    assert proc.returncode == 0, proc.stderr
    edits = [c for c in writes(calls) if c.startswith("release edit")]
    assert edits and all("--prerelease" in c and "--latest=false" in c for c in edits)
    assert not any(c.startswith("release create") for c in calls)


@pytest.mark.parametrize(
    "tag,flags",
    [("v2.0.0-beta.2", ()), ("v1.16.3", ("--channel", "beta"))],
)
def test_prerelease_tag_needs_beta_channel(tmp_path, tag, flags):
    proc, calls = run(tmp_path, tag, *flags)
    assert proc.returncode != 0 and not writes(calls)


def test_wrong_account_refuses_before_any_write(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3", FAKE_LOGIN="Example-owner")
    assert proc.returncode != 0 and not writes(calls)
    assert "NyedisAdam" in proc.stderr


def test_missing_tag_refuses_before_any_write(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3", FAKE_TAG_EXISTS="0")
    assert proc.returncode != 0 and not writes(calls)


def test_sha_mismatch_uploads_nothing(tmp_path):
    version = "1.16.3"
    dist = make_dist(tmp_path, version, f"Carnivore-{version}-arm64-mac.zip")
    (dist / f"Carnivore-{version}-arm64-mac.zip").write_bytes(b"tampered")
    proc = subprocess.run(["bash", str(SCRIPT), "v1.16.3", str(dist)], capture_output=True, text=True, timeout=60,
                          env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)})
    assert proc.returncode != 0 and "sha512" in proc.stderr


def test_dry_run_makes_no_gh_call(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3", "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert calls == []


def test_universal_refuses_arm64_zip_name(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3", "--universal")
    assert proc.returncode != 0 and not writes(calls) and "arm64" in proc.stderr
    (tmp_path / "u").mkdir()
    ok, _ = run(tmp_path / "u", "v1.16.3", "--universal", "--dry-run", zip_name="Carnivore-1.16.3-universal-mac.zip")
    assert ok.returncode == 0, ok.stderr


def test_token_never_on_argv(tmp_path):
    proc, calls = run(tmp_path, "v1.16.3")
    assert proc.returncode == 0, proc.stderr
    assert calls and SECRET not in "\n".join(calls)
