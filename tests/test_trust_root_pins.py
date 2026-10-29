
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import structlog.testing

from src.core.catalog.minisign import parse_public_key
from src.core.catalog.trust_root import (
    MIN_INDEX_SERIAL,
    TrustRoot,
    production_trust_root,
)
from src.core.catalog.verify import verify_index
from src.core.catalog.verify_types import (
    INDEX_ROLLBACK,
    SIGNATURE_INVALID,
    VerifiedIndex,
    VerifyRefusal,
)
from tests.helpers.catalog_fixture import (
    DEFAULT_GENERATED_AT,
    build_signed_index,
    skill_item,
)
from tests.helpers.minisign_keys import generate_keypair, require_minisign

PUBLISHER_KEY_ID = "3463B8E83B44738B"

INDEX_KEY_ID = "1E6D8DC5028C1DE8"

ED25519_PUBLIC_KEY_BYTES = 32


def test_the_publisher_key_is_pinned() -> None:
    trust_root = production_trust_root()
    assert trust_root.publisher_key is not None


def test_the_publisher_key_id_matches_what_minisign_printed() -> None:
    trust_root = production_trust_root()
    assert trust_root.publisher_key.key_id == PUBLISHER_KEY_ID


def test_the_publisher_key_raw_bytes_are_a_valid_ed25519_length() -> None:
    trust_root = production_trust_root()
    assert len(trust_root.publisher_key.raw) == ED25519_PUBLIC_KEY_BYTES


def test_the_index_key_is_pinned() -> None:
    trust_root = production_trust_root()
    assert trust_root.index_key is not None


def test_the_index_key_id_matches_what_minisign_printed() -> None:
    trust_root = production_trust_root()
    assert trust_root.index_key.key_id == INDEX_KEY_ID


def test_the_index_key_raw_bytes_are_a_valid_ed25519_length() -> None:
    trust_root = production_trust_root()
    assert len(trust_root.index_key.raw) == ED25519_PUBLIC_KEY_BYTES


def test_the_two_pinned_keys_are_different_keys() -> None:
    trust_root = production_trust_root()
    assert trust_root.index_key.key_id != trust_root.publisher_key.key_id


def test_no_unpinned_warning_is_emitted() -> None:
    with structlog.testing.capture_logs() as captured:
        production_trust_root()
    assert [
        entry for entry in captured
        if entry["event"] == "catalog_trust_root_unpinned"
    ] == []


def test_an_index_signed_by_another_key_is_refused_by_the_shipped_root(
    tmp_path: Path,
) -> None:
    require_minisign()
    index_directory = tmp_path / "index"
    publisher_directory = tmp_path / "publisher"
    index_directory.mkdir()
    publisher_directory.mkdir()
    index_keypair = generate_keypair(index_directory)
    publisher_keypair = generate_keypair(publisher_directory)
    signed = build_signed_index(
        tmp_path,
        index_keypair=index_keypair,
        publisher_keypair=publisher_keypair,
        items=[skill_item("work", "alex", "ab" * 32)],
    )

    result = verify_index(
        signed.index_bytes,
        signed.minisig_text,
        trust_root=production_trust_root(),
        seen_revocations=frozenset(),
        last_verified_serial=0,
        now=DEFAULT_GENERATED_AT + timedelta(days=1),
        consented_serial=None,
    )

    assert isinstance(result, VerifyRefusal), f"expected a refusal, got {result}"
    assert result.code == SIGNATURE_INVALID
    assert "not the pinned index key" in result.detail


LIVE_CHECKED_SERIAL = 3


def test_the_rollback_floor_is_the_serial_the_live_check_printed() -> None:
    assert MIN_INDEX_SERIAL == LIVE_CHECKED_SERIAL


def test_the_shipped_floor_reaches_the_verifier() -> None:
    assert production_trust_root().min_index_serial == LIVE_CHECKED_SERIAL


def test_an_index_one_serial_below_the_shipped_floor_is_refused(
    tmp_path: Path,
) -> None:
    require_minisign()
    index_directory = tmp_path / "floor-index"
    publisher_directory = tmp_path / "floor-publisher"
    index_directory.mkdir()
    publisher_directory.mkdir()
    index_keypair = generate_keypair(index_directory)
    publisher_keypair = generate_keypair(publisher_directory)
    trust_root = TrustRoot(
        index_key=parse_public_key(index_keypair.public_key_text),
        publisher_key=parse_public_key(publisher_keypair.public_key_text),
        min_index_serial=MIN_INDEX_SERIAL,
    )

    def run_at(serial: int):
        signed = build_signed_index(
            tmp_path,
            index_keypair=index_keypair,
            publisher_keypair=publisher_keypair,
            items=[skill_item("work", "alex", "ab" * 32)],
            serial=serial,
        )
        return verify_index(
            signed.index_bytes,
            signed.minisig_text,
            trust_root=trust_root,
            seen_revocations=frozenset(),
            last_verified_serial=0,
            now=DEFAULT_GENERATED_AT + timedelta(days=1),
            consented_serial=None,
        )

    below = run_at(MIN_INDEX_SERIAL - 1)
    assert isinstance(below, VerifyRefusal), f"expected a refusal, got {below}"
    assert below.code == INDEX_ROLLBACK

    at_floor = run_at(MIN_INDEX_SERIAL)
    assert isinstance(at_floor, VerifiedIndex), f"expected a pass, got {at_floor}"
    assert at_floor.serial == MIN_INDEX_SERIAL


def test_unpinned_spare_warns_once_per_process(monkeypatch) -> None:
    from structlog.testing import capture_logs

    from src.core.catalog import trust_root as trust_root_module

    monkeypatch.setattr(trust_root_module, "_WARNED", frozenset())
    monkeypatch.setattr(
        trust_root_module, "SPARE_INDEX_PUBLIC_KEY", trust_root_module.SPARE_INDEX_KEY_PLACEHOLDER,
    )
    with capture_logs() as logs:
        for _ in range(5):
            production_trust_root()
    fired = [e for e in logs if e["event"] == "catalog_spare_index_key_unpinned"]
    assert len(fired) == 1
