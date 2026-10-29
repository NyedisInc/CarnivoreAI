
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src.core.catalog.minisign import parse_public_key, parse_signature, verify
from src.core.catalog.revocation import revoke_statement
from src.core.skills.digest import digest_directory
from src.models.catalog_statement import release_statement
from tests.helpers.minisign_keys import Keypair, generate_keypair, minisign_binary

BOOTSTRAP = Path(__file__).resolve().parents[1] / "scripts" / "catalog-bootstrap"

HANDLE = "nyedis"
SKILL = "work"
SLUG = "NyedisInc/CarnivoreAI-Catalog"

SKILL_MD = """---
name: work
description: reads the repository and says what is free to pick up.
---

# work

open the issue list and claim one with a draft pull request.
"""

requires_minisign = pytest.mark.skipif(
    minisign_binary() is None,
    reason="the real minisign binary is not installed; brew install minisign. "
           "this is a check that could not run, which is not a check that passed",
)


def load_script(name: str) -> Any:
    if str(BOOTSTRAP) not in sys.path:
        sys.path.insert(0, str(BOOTSTRAP))
    spec = importlib.util.spec_from_file_location(name, BOOTSTRAP / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"git {args}: {result.stderr}"
    return result.stdout.strip()


@pytest.fixture
def catalog(tmp_path: Path) -> dict:
    root = tmp_path / "catalog"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "test")
    (root / "catalog.yml").write_text(
        f"repo: {SLUG}\nmin_serial: 1\nstaleness_days: 30\n"
        f"review_model: test/model\nreview_max_chars: 40000\n",
        encoding="utf-8",
    )
    skill = root / "skills" / HANDLE / SKILL
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "publish work")
    commit = git(root, "rev-parse", "HEAD")
    digest, _entries = digest_directory(skill)
    return {"root": root, "commit": commit, "digest": digest}


@requires_minisign
def test_sign_release_writes_a_signature_the_app_verifies(
    catalog: dict, tmp_path: Path,
) -> None:
    keys: Keypair = generate_keypair(tmp_path)
    module = load_script("sign_release")
    code = module.main([
        "--catalog", str(catalog["root"]),
        "--handle", HANDLE, "--name", SKILL, "--version", "1.0.0",
        "--commit", catalog["commit"], "--key", str(keys.sec_path),
    ])
    assert code == 0

    written = catalog["root"] / "releases" / HANDLE / SKILL / "1.0.0.json"
    payload = json.loads(written.read_text(encoding="utf-8"))

    expected = release_statement(
        kind="skill", publisher=HANDLE, name=SKILL, version="1.0.0",
        repo=SLUG, path=f"skills/{HANDLE}/{SKILL}",
        commit=catalog["commit"], digest=catalog["digest"],
    )
    assert payload["statement"].encode("utf-8") == expected, (
        "the bytes signed are not the bytes the app re-renders to verify"
    )
    assert payload["commit"] == catalog["commit"]
    assert payload["digest"] == catalog["digest"]
    assert set(payload["sig"]) == {"key_id", "sig", "tc", "gsig"}

    key = parse_public_key(keys.public_key_text)
    assert payload["sig"]["key_id"] == key.key_id
    rebuilt = (
        "untrusted comment: x\n"
        f"{payload['sig']['sig']}\n"
        f"trusted comment: {payload['sig']['tc']}\n"
        f"{payload['sig']['gsig']}\n"
    )
    assert verify(expected, parse_signature(rebuilt), key, expect_prehashed=True)


@requires_minisign
def test_sign_release_refuses_a_commit_that_is_not_there(
    catalog: dict, tmp_path: Path,
) -> None:
    keys: Keypair = generate_keypair(tmp_path)
    module = load_script("sign_release")
    code = module.main([
        "--catalog", str(catalog["root"]),
        "--handle", HANDLE, "--name", SKILL, "--version", "1.0.0",
        "--commit", "a" * 40, "--key", str(keys.sec_path),
    ])
    assert code == 1
    assert not (catalog["root"] / "releases").exists(), (
        "nothing may be written when the commit could not be resolved"
    )


@requires_minisign
def test_sign_release_refuses_a_skill_folder_that_is_not_there(
    catalog: dict, tmp_path: Path,
) -> None:
    keys: Keypair = generate_keypair(tmp_path)
    module = load_script("sign_release")
    code = module.main([
        "--catalog", str(catalog["root"]),
        "--handle", HANDLE, "--name", "absent", "--version", "1.0.0",
        "--commit", catalog["commit"], "--key", str(keys.sec_path),
    ])
    assert code == 1


@requires_minisign
def test_revoke_writes_a_statement_the_app_verifies(tmp_path: Path) -> None:
    keys: Keypair = generate_keypair(tmp_path)
    module = load_script("revoke")
    store = tmp_path / "meta"
    store.mkdir()
    code = module.main([
        "--meta", str(store), "--handle", HANDLE,
        "--kind", "version", "--subject", f"{HANDLE}/{SKILL}@1.0.0",
        "--since", "2026-09-15", "--key", str(keys.sec_path), "--clone", str(tmp_path),
    ], start_build=lambda: "build-fake", marketplace=lambda clone, revocations, store: "m1", check_clone=lambda c: None)
    assert code == 0

    written = (
        store / "revocations" / HANDLE
        / f"version-{HANDLE}-{SKILL}-1.0.0.json"
    )
    payload = json.loads(written.read_text(encoding="utf-8"))
    expected = revoke_statement(
        kind="version", subject=f"{HANDLE}/{SKILL}@1.0.0", since="2026-09-15",
    )
    assert payload["statement"].encode("utf-8") == expected
    key = parse_public_key(keys.public_key_text)
    assert verify(
        expected, parse_signature(payload["sig"]), key, expect_prehashed=True,
    ), "the revocation this wrote would be ignored by every client"


@requires_minisign
def test_revoke_starts_the_index_build_once_after_the_store_write(tmp_path: Path) -> None:
    keys: Keypair = generate_keypair(tmp_path)
    module = load_script("revoke")
    store = tmp_path / "meta"
    store.mkdir()
    seen: list[bool] = []
    target = store / "revocations" / HANDLE / f"version-{HANDLE}-{SKILL}-1.0.0.json"
    args = ["--meta", str(store), "--handle", HANDLE, "--kind", "version",
            "--subject", f"{HANDLE}/{SKILL}@1.0.0", "--since", "2026-09-15", "--key", str(keys.sec_path),
            "--clone", str(tmp_path)]
    assert module.main(args, start_build=lambda: seen.append(target.exists()) or "build-1",
                       marketplace=lambda clone, revocations, store: "m1", check_clone=lambda c: None) == 0
    assert seen == [True]
    seen.clear()
    assert module.main(args, start_build=lambda: seen.append(True), marketplace=lambda c, r, s: "m1", check_clone=lambda c: None) == 1
    assert seen == []


@requires_minisign
def test_version_revoke_pushes_the_marketplace_commit_or_refuses_to_finish(tmp_path: Path, capsys) -> None:
    keys: Keypair = generate_keypair(tmp_path)
    module = load_script("revoke")
    store = tmp_path / "meta"
    store.mkdir()
    args = ["--meta", str(store), "--handle", HANDLE, "--kind", "version", "--subject", f"{HANDLE}/{SKILL}@1.0.0",
            "--since", "2026-09-15", "--key", str(keys.sec_path)]
    assert module.main(args, start_build=lambda: pytest.fail("no build")) == 1
    assert "--clone" in capsys.readouterr().err and list(store.rglob("*")) == []
    assert module.main([*args, "--clone", str(tmp_path)], start_build=lambda: pytest.fail("no build")) == 1
    assert "origin" in capsys.readouterr().err and list(store.rglob("*")) == []
    order: list[str] = []
    target = f"revocations/{HANDLE}/version-{HANDLE}-{SKILL}-1.0.0.json"

    def broken(clone: Path, revocations: dict, store: object) -> str:
        assert list(revocations) == [target]
        raise RuntimeError("push rejected")

    clone_args = [*args, "--clone", str(tmp_path)]
    assert module.main(clone_args, start_build=lambda: pytest.fail("no build"), marketplace=broken, check_clone=lambda c: None) == 1
    assert "--marketplace-only" in capsys.readouterr().err and (store / target).exists()
    assert module.main([*clone_args, "--marketplace-only"], start_build=lambda: order.append("build") or "b",
                       marketplace=lambda clone, revocations, store: order.append("market") or "m1", check_clone=lambda c: None) == 0
    assert order == ["market", "build"]


def test_revoke_refuses_a_version_subject_with_no_version(tmp_path: Path) -> None:
    module = load_script("revoke")
    store = tmp_path / "meta"
    store.mkdir()
    code = module.main([
        "--meta", str(store), "--handle", HANDLE,
        "--kind", "version", "--subject", "nyedis/work",
        "--since", "2026-09-15",
    ], start_build=lambda: pytest.fail("a refused revocation must not start the build"))
    assert code == 1
    assert list(store.rglob("*")) == [], "a refusal must write nothing to the store"


def test_revoke_refuses_a_date_that_is_not_a_date(tmp_path: Path) -> None:
    module = load_script("revoke")
    store = tmp_path / "meta"
    store.mkdir()
    code = module.main([
        "--meta", str(store), "--handle", HANDLE,
        "--kind", "key", "--subject", "3463B8E83B44738B",
        "--since", "yesterday",
    ], start_build=lambda: pytest.fail("a refused revocation must not start the build"))
    assert code == 1
    assert list(store.rglob("*")) == [], "a refusal must write nothing to the store"


def test_the_repo_slug_comes_from_the_catalog_and_not_from_a_flag(
    catalog: dict,
) -> None:
    common = load_script("_common")
    assert common.repo_slug(catalog["root"]) == SLUG

    (catalog["root"] / "catalog.yml").write_text("min_serial: 1\n", encoding="utf-8")
    with pytest.raises(common.HelperError):
        common.repo_slug(catalog["root"])


@requires_minisign
def test_the_signature_fields_name_the_key_that_made_them(tmp_path: Path) -> None:
    common = load_script("_common")
    keys: Keypair = generate_keypair(tmp_path)
    block, text = common.sign_statement(b"carnivore-test\n", keys.sec_path)
    assert block["key_id"] == parse_public_key(keys.public_key_text).key_id
    assert block["sig"] == [ln for ln in text.splitlines() if ln.strip()][1].strip()
    assert "trusted comment:" not in block["tc"], (
        "the trusted comment is carried without its prefix"
    )


def test_a_malformed_signature_file_is_refused() -> None:
    common = load_script("_common")
    with pytest.raises(common.HelperError):
        common.signature_fields("untrusted comment: x\nnot-base64\n")
