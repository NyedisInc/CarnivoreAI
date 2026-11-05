
from __future__ import annotations

import base64
import os
import sqlite3
import subprocess
from pathlib import Path
from typing import List

import pytest

from src.core.pack.transport import publish

_ALPHABET = "aB3dE5fG7hJ9kL1mN2pQ4rS6tU8vW0xY2zA4cD6e"
TOKEN = "gh" + "p_" + _ALPHABET[:36]


@pytest.fixture(autouse=True)
def _sealed_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.startswith("GIT_")]:
        monkeypatch.delenv(name)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))


def _repo(root: Path) -> str:
    subprocess.run(["git", "-C", str(root), "init", "-q", "-b", "main"], check=True)
    return str(root)


def _scan(root: Path) -> List[str]:
    return publish.scan_for_secrets(_repo(root))


def test_planted_token_is_flagged_by_name(tmp_path: Path) -> None:
    (tmp_path / "app.env.txt").write_text(f"GH_TOKEN={TOKEN}\n")
    (tmp_path / "readme.md").write_text("hello\n")
    flagged = _scan(tmp_path)
    assert flagged == ["app.env.txt"]


def test_clean_tree_passes(tmp_path: Path) -> None:
    (tmp_path / "main.py").write_text("print('hi')\n")
    (tmp_path / "notes.md").write_text("nothing here\n")
    assert _scan(tmp_path) == []


def test_gitignored_secret_is_not_scanned(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("secret.txt\n")
    (tmp_path / "secret.txt").write_text(f"{TOKEN}\n")
    assert _scan(tmp_path) == []


def test_unreadable_file_is_refused_as_unscannable_and_named(tmp_path: Path) -> None:
    target = tmp_path / "locked.txt"
    target.write_text("data\n")
    target.chmod(0)
    try:
        if target.read_bytes():
            pytest.skip("file permissions are not enforced for this user")
    except PermissionError:
        pass
    try:
        with pytest.raises(publish.PublishRefused) as err:
            _scan(tmp_path)
        assert err.value.code == "unscannable_files"
        assert err.value.files == ["locked.txt"]
    finally:
        target.chmod(0o600)


def test_listing_failure_refuses_the_publish(tmp_path: Path) -> None:
    with pytest.raises(publish.PublishRefused) as err:
        publish.scan_for_secrets(str(tmp_path))
    assert err.value.code == "scan_failed"


def test_png_with_no_secret_passes(tmp_path: Path) -> None:
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(range(256)) * 64)
    assert _scan(tmp_path) == []


def test_token_inside_a_binary_file_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\x00\xc3\xff" + TOKEN.encode() + b"\xc3\x00")
    assert _scan(tmp_path) == ["blob.bin"]


def test_token_inside_a_two_mib_file_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "dump.txt").write_text("x" * (2 * 1024 * 1024) + f"\nGH_TOKEN={TOKEN}\n")
    assert _scan(tmp_path) == ["dump.txt"]


@pytest.mark.parametrize("offset", [1, 20, 36])
def test_token_straddling_a_chunk_boundary_is_flagged(tmp_path: Path, offset: int) -> None:
    cut = publish.SCAN_CHUNK_BYTES - offset
    (tmp_path / "edge.txt").write_bytes(b" " * cut + TOKEN.encode() + b" " * 4096)
    assert _scan(tmp_path) == ["edge.txt"]


def test_budget_is_checked_before_any_file_is_read_and_names_the_largest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish, "MAX_TOTAL_SCAN_BYTES", 100)
    (tmp_path / "a.txt").write_text("a" * 10)
    (tmp_path / "big.mov").write_text("b" * 90)
    (tmp_path / "mid.bin").write_text("c" * 40)
    reads: List[Path] = []
    real = publish._file_holds_secret
    monkeypatch.setattr(publish, "_file_holds_secret", lambda path, remaining: reads.append(path) or real(path, remaining))
    with pytest.raises(publish.PublishRefused) as err:
        _scan(tmp_path)
    assert err.value.code == "scan_budget_exceeded"
    assert err.value.files == ["big.mov", "mid.bin", "a.txt"]
    assert reads == []


def test_budget_backstop_stops_a_file_that_grows_while_scanned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "grows.txt").write_text("x" * 50)
    monkeypatch.setattr(publish, "_listed_sizes", lambda root, listing: [("grows.txt", 1)])
    monkeypatch.setattr(publish, "MAX_TOTAL_SCAN_BYTES", 10)
    with pytest.raises(publish.PublishRefused) as err:
        _scan(tmp_path)
    assert err.value.code == "scan_budget_exceeded"
    assert err.value.files == ["grows.txt"]


def test_symlinks_and_directories_are_never_named_in_the_budget_refusal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish, "MAX_TOTAL_SCAN_BYTES", 10)
    (tmp_path / "big.txt").write_text("b" * 50)
    (tmp_path / "link.txt").symlink_to(tmp_path / "big.txt")
    with pytest.raises(publish.PublishRefused) as err:
        _scan(tmp_path)
    assert err.value.files == ["big.txt"]


def test_gitignored_big_or_binary_file_is_still_skipped(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("big.log\nblob.bin\n")
    (tmp_path / "big.log").write_text(f"{TOKEN}\n" + "x" * (2 * publish.SCAN_CHUNK_BYTES))
    (tmp_path / "blob.bin").write_bytes(b"\x00" + TOKEN.encode())
    assert _scan(tmp_path) == []


def test_a_secret_hit_outranks_an_unreadable_file(tmp_path: Path) -> None:
    (tmp_path / "keys.txt").write_text(f"{TOKEN}\n")
    locked = tmp_path / "locked.txt"
    locked.write_text("x")
    locked.chmod(0)
    try:
        if os.access(locked, os.R_OK):
            pytest.skip("file permissions are not enforced for this user")
        assert _scan(tmp_path) == ["keys.txt"]
    finally:
        locked.chmod(0o600)


@pytest.mark.parametrize("code", ["secrets_found", "unscannable_files", "scan_budget_exceeded", "scan_failed"])
def test_each_scan_refusal_has_its_own_plain_sentence(code: str) -> None:
    from src.api.error_response import sentence_for

    assert sentence_for(code, 409) != sentence_for("no_such_code_xyz", 409)
    assert "nothing was published" in sentence_for(code, 409)


def test_scan_failed_says_the_listing_failed_and_the_budget_sentence_names_limit_and_remedy() -> None:
    from src.api.error_response import sentence_for

    assert "listed" in sentence_for("scan_failed", 409)
    budget = sentence_for("scan_budget_exceeded", 409)
    assert "{limit}" in budget and "ignore" in budget
    filled = publish.fill_params(budget, publish.budget_params())
    assert f"{publish.MAX_TOTAL_SCAN_BYTES // (1024 * 1024)} MiB" in filled and "{" not in filled


def test_the_refusal_body_names_at_most_the_cap_and_counts_the_rest() -> None:
    names = [f"f{i}.bin" for i in range(publish.MAX_LISTED_FILES + 7)]
    assert publish.listed_files(names) == {"files": names[: publish.MAX_LISTED_FILES], "files_more": 7}
    assert publish.listed_files(["a"]) == {"files": ["a"], "files_more": 0}


def test_token_touching_letters_in_a_binary_file_is_flagged(tmp_path: Path) -> None:
    token = TOKEN.encode()
    (tmp_path / "before.bin").write_bytes(b"\x00alice" + token + b"\x00")
    (tmp_path / "utf8_before.bin").write_bytes(b"\x00\xc3\xa9" + token + b"\x00")
    (tmp_path / "utf8_after.bin").write_bytes(b"\x00" + token + b"\xc3\xa9\x00")
    assert sorted(_scan(tmp_path)) == ["before.bin", "utf8_after.bin", "utf8_before.bin"]


def test_token_in_a_real_sqlite_file_is_flagged(tmp_path: Path) -> None:
    db = sqlite3.connect(tmp_path / "app.db")
    db.execute("create table t(name text, tok text)")
    db.execute("insert into t values (?, ?)", ("alice", TOKEN))
    db.commit()
    db.close()
    assert _scan(tmp_path) == ["app.db"]


def test_a_three_kib_jwt_straddling_the_chunk_boundary_is_flagged(tmp_path: Path) -> None:
    def part(n: int) -> str:
        return base64.urlsafe_b64encode(bytes((i * 7 + n) % 251 for i in range(n))).decode().rstrip("=")
    jwt = "eyJ" + part(60) + ".eyJ" + part(2100) + "." + part(48)
    assert len(jwt) > 2800
    cut = publish.SCAN_CHUNK_BYTES - 1100
    (tmp_path / "token.txt").write_bytes(b" " * cut + jwt.encode() + b" " * 4096)
    assert _scan(tmp_path) == ["token.txt"]


def test_identifier_text_in_a_binary_file_is_not_flagged(tmp_path: Path) -> None:
    table = b"\x00copyProps__reExport__toESM__toCommonJS__exportAll\x00propsprops_unionAllInvalidInputAbcdefghij1234567890\x00"
    table += b"\x00runTask_test_ValidatesEveryPartitionQuickly\x00Disk_live_SnapshotRestoreHandlerImpl\x00"
    table += b"\x00task-admin-dashboard-settings-panel-container-wrapper\x00risk-proj-overview-summary-table-header-cell-label-text\x00"
    (tmp_path / "native.node").write_bytes(b"\x7fELF\x00" + table * 4)
    assert _scan(tmp_path) == []


def test_token_in_a_utf16_file_is_flagged(tmp_path: Path) -> None:
    line = f"GH_TOKEN={TOKEN}\r\n"
    cjk = "\u4e2d\u6587\u8a00\u8a9e" * 1000
    (tmp_path / "with_bom.txt").write_bytes(b"\xff\xfe" + line.encode("utf-16-le"))
    (tmp_path / "no_bom.txt").write_bytes(line.encode("utf-16-le"))
    (tmp_path / "big_endian.txt").write_bytes(b"\xfe\xff" + line.encode("utf-16-be"))
    (tmp_path / "cjk_no_bom.txt").write_bytes((cjk + line).encode("utf-16-le"))
    (tmp_path / "cjk_bom.txt").write_bytes(b"\xff\xfe" + (cjk + line).encode("utf-16-le"))
    assert sorted(_scan(tmp_path)) == ["big_endian.txt", "cjk_bom.txt", "cjk_no_bom.txt", "no_bom.txt", "with_bom.txt"]


def test_token_in_a_utf16_file_past_the_first_window_is_flagged(tmp_path: Path) -> None:
    cjk = "\u4e2d\u6587\u8a00\u8a9e" * 150_000
    (tmp_path / "long.txt").write_bytes(b"\xff\xfe" + (cjk + f"GH_TOKEN={TOKEN}\r\n").encode("utf-16-le"))
    assert _scan(tmp_path) == ["long.txt"]


def test_glued_token_before_a_late_nul_is_flagged(tmp_path: Path) -> None:
    body = b"alice" + TOKEN.encode() + b" " * (2 * publish.SCAN_CHUNK_BYTES) + b"\x00"
    (tmp_path / "late.bin").write_bytes(body)
    assert _scan(tmp_path) == ["late.bin"]


def test_compressed_members_are_scanned_as_raw_bytes_only(tmp_path: Path) -> None:
    import io
    import zipfile

    for name, method in (("deflated.zip", zipfile.ZIP_DEFLATED), ("stored.zip", zipfile.ZIP_STORED)):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", method) as archive:
            archive.writestr(".env", f"GH_TOKEN={TOKEN}\n")
        (tmp_path / name).write_bytes(buffer.getvalue())
    assert _scan(tmp_path) == ["stored.zip"]


def _mixed(length: int, seed: int) -> str:
    import random
    rng = random.Random(seed)
    body = [rng.choice("abcdefghijklmnopqrstuvwxyz"), rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ"), rng.choice("0123456789")]
    body += [rng.choice("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(length - 3)]
    rng.shuffle(body)
    return "".join(body)


@pytest.mark.parametrize("name,token", [("stripe_secret", "sk_" + "live_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"),
                                        ("openai_api_key", "sk-" + "proj-" + _mixed(48, 5))],
                         ids=["stripe_secret", "openai_api_key"])
def test_mixed_case_digit_token_glued_in_a_sqlite_file_is_found(tmp_path: Path, name: str, token: str) -> None:
    db = sqlite3.connect(tmp_path / "app.db")
    db.execute("create table t(name text, tok text)")
    db.execute("insert into t values (?, ?)", (name, token))
    db.commit()
    db.close()
    assert _scan(tmp_path) == ["app.db"]


def test_utf16_file_holding_contextual_secrets_is_flagged(tmp_path: Path) -> None:
    cases = {
        "aws.txt": f"aws_secret_access_key = {_mixed(40, 1)}\r\n",
        "password.txt": f"password={_mixed(24, 2)}\r\n",
        "ops.txt": f"OP_TOKEN=ops_{_mixed(60, 3)}\r\n",
        "bearer.txt": f"Authorization: Bearer {_mixed(40, 4)}\r\n",
    }
    for name, line in cases.items():
        (tmp_path / name).write_bytes(b"\xff\xfe" + line.encode("utf-16-le"))
    assert sorted(_scan(tmp_path)) == sorted(cases)
