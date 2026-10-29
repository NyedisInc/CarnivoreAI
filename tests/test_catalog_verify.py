
from __future__ import annotations

import copy
import io
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import pytest
import structlog.testing
from pydantic import ValidationError

from src.core.catalog.minisign import parse_public_key
from src.core.catalog.revocation import RevocationRef, revoke_statement
from src.core.catalog.trust_root import TrustRoot, production_trust_root
from src.core.catalog.verify import check_digest, check_scripts, verify_index
from src.core.catalog.verify_items import verify_item
from src.core.catalog.verify_types import (
    DIGEST_MISMATCH,
    INDEX_NOT_JSON,
    INDEX_ROLLBACK,
    INDEX_SERIAL_JUMP,
    ITEM_SCHEMA_DETAIL_PREFIX,
    KEY_UNTRUSTED,
    NAME_RESERVED,
    SCRIPTS_NOT_SUPPORTED,
    SIGNATURE_INVALID,
    VERSION_REVOKED,
    VerifiedIndex,
    VerifyRefusal,
)
from src.core.skills.stage import stage_archive
from tests.helpers.catalog_fixture import (
    DEFAULT_GENERATED_AT,
    SignedIndex,
    build_signed_index,
    impersonating_public_key,
    public_key_line,
    revocation_entry,
    seal,
    sign_bytes,
    sign_bytes_legacy,
    sign_item_versions,
    skill_item,
)
from tests.helpers.minisign_keys import Keypair, generate_keypair, require_minisign

PUBLISHER = "acme"
SKILL = "work"
ITEM_ID = f"{PUBLISHER}/{SKILL}"
DIGEST = "ab" * 32

NOW = DEFAULT_GENERATED_AT + timedelta(days=1)


@dataclass(frozen=True)
class Keys:

    index: Keypair
    publisher: Keypair
    attacker: Keypair
    third: Keypair


@pytest.fixture(scope="session")
def keys(tmp_path_factory: pytest.TempPathFactory) -> Keys:
    require_minisign()
    base = tmp_path_factory.mktemp("catalog-keys")
    made = {}
    for role in ("index", "publisher", "attacker", "third"):
        directory = base / role
        directory.mkdir()
        made[role] = generate_keypair(directory)
    return Keys(**made)


@pytest.fixture
def trust_root(keys: Keys) -> TrustRoot:
    return TrustRoot(
        index_key=parse_public_key(keys.index.public_key_text),
        publisher_key=parse_public_key(keys.publisher.public_key_text),
    )


def publisher_key_id(keys: Keys) -> str:
    return parse_public_key(keys.publisher.public_key_text).key_id


def good_index(
    tmp_path: Path, keys: Keys, **kwargs: Any
) -> SignedIndex:
    kwargs.setdefault("items", [skill_item(SKILL, PUBLISHER, DIGEST)])
    return build_signed_index(
        tmp_path,
        index_keypair=keys.index,
        publisher_keypair=keys.publisher,
        **kwargs,
    )


def run(
    signed: SignedIndex,
    trust_root: TrustRoot,
    *,
    now: Optional[datetime] = None,
    seen: frozenset = frozenset(),
    last_serial: int = 0,
    minisig: Optional[str] = None,
    consented: Optional[int] = None,
) -> Any:
    return verify_index(
        signed.index_bytes,
        signed.minisig_text if minisig is None else minisig,
        trust_root=trust_root,
        seen_revocations=seen,
        last_verified_serial=last_serial,
        now=now or NOW,
        consented_serial=consented,
    )


def refusal_of(result: Any) -> VerifyRefusal:
    assert isinstance(result, VerifyRefusal), f"expected a refusal, got {result}"
    return result


def verified(result: Any) -> VerifiedIndex:
    assert isinstance(result, VerifiedIndex), f"expected success, got {result}"
    return result


def only_refused(result: Any) -> Any:
    index = verified(result)
    assert len(index.refused) == 1, index.refused
    return index.refused[0]




def test_a_correctly_signed_index_verifies(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    index = verified(run(good_index(tmp_path, keys), trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert index.untrusted_items == ()
    assert index.refused == ()
    assert index.revocations == ()
    assert index.degraded is False
    assert index.serial == 1
    assert index.index_key_id == parse_public_key(keys.index.public_key_text).key_id
    assert index.generated_at == DEFAULT_GENERATED_AT


def test_additive_item_fields_verify_and_an_index_without_them_still_does(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    extra = {
        "cost": {"desc_tokens": 12, "body_tokens": 340, "estimator": "chars/4"},
        "fm_keys": ["allowed-tools", "description", "name"],
        "related": ["someone/other"],
        "deprecated": {"superseded_by": "someone/other"},
    }
    with_fields = good_index(
        tmp_path, keys, items=[skill_item(SKILL, PUBLISHER, DIGEST, extra=extra)]
    )
    item = verified(run(with_fields, trust_root)).items[0]
    assert item.cost is not None and item.cost.body_tokens == 340
    assert item.fm_keys == extra["fm_keys"]
    assert item.related == ["someone/other"]
    assert item.deprecated is not None
    assert item.deprecated.superseded_by == "someone/other"
    assert item.model_dump(mode="json")["cost"]["desc_tokens"] == 12

    plain = verified(run(good_index(tmp_path, keys), trust_root)).items[0]
    assert plain.cost is None and plain.fm_keys is None
    assert plain.related is None and plain.deprecated is None


def test_a_version_carrying_scripts_is_still_listed(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(
        tmp_path, keys, items=[skill_item(SKILL, PUBLISHER, DIGEST, scripts=3)]
    )
    assert [item.id for item in verified(run(signed, trust_root)).items] == [ITEM_ID]


@pytest.mark.parametrize("verdict", ["flagged", "blocked"])
def test_a_review_kind_this_build_does_not_know_keeps_the_item_listed(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot, verdict: str
) -> None:
    item = skill_item(SKILL, PUBLISHER, DIGEST)
    item["versions"][0]["review"] = {
        "status": "reviewed",
        "verdict": verdict,
        "warnings": [{"kind": "future_kind", "detail": "a newer finding"}],
    }
    signed = good_index(tmp_path, keys, items=[item])
    index = verified(run(signed, trust_root))
    assert [i.id for i in index.items] == [ITEM_ID]
    assert index.refused == ()
    review = index.items[0].versions[0].review
    assert review.verdict == verdict
    assert review.warnings[0].kind == "future_kind"


def _skill_tarball(tmp_path: Path, body: bytes, name: str) -> Path:
    root = f"catalog-abc123/skills/{PUBLISHER}/{SKILL}/"
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        info = tarfile.TarInfo(f"{root}SKILL.md")
        info.mode = 0o644
        info.size = len(body)
        tar.addfile(info, io.BytesIO(body))
    path = tmp_path / name
    path.write_bytes(buffer.getvalue())
    return path


def _stage(tmp_path: Path, body: bytes, label: str) -> str:
    archive = _skill_tarball(tmp_path, body, f"{label}.tar.gz")
    staged = stage_archive(
        archive, tmp_path / label, publisher=PUBLISHER, name=SKILL
    )
    return staged.digest


def test_one_flipped_byte_in_the_staged_skill_is_a_digest_mismatch(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed_digest = _stage(tmp_path, b"# the work skill\n", "honest")
    signed = good_index(
        tmp_path, keys, items=[skill_item(SKILL, PUBLISHER, signed_digest)]
    )
    index = verified(run(signed, trust_root))
    assert index.items[0].versions[0].digest == signed_digest
    assert check_digest(signed_digest, signed_digest) is None

    tampered = _stage(tmp_path, b"# the w0rk skill\n", "tampered")
    assert tampered != signed_digest
    mismatch = check_digest(signed_digest, tampered)
    assert mismatch is not None and mismatch.code == DIGEST_MISMATCH




@pytest.mark.parametrize("minisig", ["", "   ", "not a signature at all"])
def test_an_unsigned_index_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot, minisig: str
) -> None:
    result = refusal_of(run(good_index(tmp_path, keys), trust_root, minisig=minisig))
    assert result.code == SIGNATURE_INVALID
    assert "malformed" in result.detail


def test_an_index_signed_by_another_key_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    forged = build_signed_index(
        tmp_path,
        index_keypair=keys.attacker,
        publisher_keypair=keys.publisher,
        items=[skill_item(SKILL, PUBLISHER, DIGEST)],
    )
    result = refusal_of(run(forged, trust_root))
    assert result.code == SIGNATURE_INVALID
    assert "not the pinned index key" in result.detail


def test_a_legacy_signature_over_the_index_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    legacy = sign_bytes_legacy(tmp_path, keys.index, signed.index_bytes)
    result = refusal_of(run(signed, trust_root, minisig=legacy))
    assert result.code == SIGNATURE_INVALID
    assert "legacy" in result.detail


def test_an_edited_body_no_longer_verifies(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    tampered = SignedIndex(
        index_bytes=signed.index_bytes.replace(b'"serial":1', b'"serial":2'),
        minisig_text=signed.minisig_text,
        document=signed.document,
    )
    assert tampered.index_bytes != signed.index_bytes
    result = refusal_of(run(tampered, trust_root))
    assert result.code == SIGNATURE_INVALID
    assert "does not verify" in result.detail


def test_the_shipped_trust_root_refuses_the_fixture(
    tmp_path: Path, keys: Keys
) -> None:
    result = refusal_of(run(good_index(tmp_path, keys), production_trust_root()))
    assert result.code == SIGNATURE_INVALID
    assert "not the pinned index key" in result.detail


def test_a_trust_root_pinning_a_different_real_key_refuses(
    tmp_path: Path, keys: Keys
) -> None:
    elsewhere = TrustRoot(
        index_key=parse_public_key(keys.third.public_key_text),
        publisher_key=parse_public_key(keys.publisher.public_key_text),
    )
    result = refusal_of(run(good_index(tmp_path, keys), elsewhere))
    assert result.code == SIGNATURE_INVALID
    assert "not the pinned index key" in result.detail




def test_a_body_that_is_not_an_index_is_not_a_forgery(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = seal(tmp_path, {"schema": "something/else"}, keys.index)
    assert refusal_of(run(signed, trust_root)).code == INDEX_NOT_JSON


def test_an_older_serial_is_a_rollback(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys, serial=6)
    result = refusal_of(run(signed, trust_root, last_serial=7))
    assert result.code == INDEX_ROLLBACK


def test_the_same_serial_again_is_fine(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys, serial=7)
    assert verified(run(signed, trust_root, last_serial=7)).serial == 7


def test_the_pinned_minimum_serial_is_a_floor_of_its_own(
    tmp_path: Path, keys: Keys
) -> None:
    root = TrustRoot(
        index_key=parse_public_key(keys.index.public_key_text),
        publisher_key=parse_public_key(keys.publisher.public_key_text),
        min_index_serial=50,
    )
    signed = good_index(tmp_path, keys, serial=10)
    assert refusal_of(run(signed, root, last_serial=0)).code == INDEX_ROLLBACK


def test_a_serial_jump_above_a_real_floor_needs_consent(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    over = good_index(tmp_path, keys, serial=5 + 1001)
    assert refusal_of(run(over, trust_root, last_serial=5)).code == INDEX_SERIAL_JUMP

    at_limit = good_index(tmp_path, keys, serial=5 + 1000)
    assert verified(run(at_limit, trust_root, last_serial=5)).serial == 1005


def test_an_ordinary_first_serial_is_not_a_jump(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys, serial=900)
    assert verified(run(signed, trust_root, last_serial=0)).serial == 900


def test_a_huge_first_serial_is_a_jump_even_from_a_zero_floor(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys, serial=2 ** 63)
    assert refusal_of(run(signed, trust_root, last_serial=0)).code == INDEX_SERIAL_JUMP


def test_consent_opens_the_ceiling_for_one_exact_serial(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys, serial=2 ** 63)
    ok = verified(run(signed, trust_root, last_serial=0, consented=2 ** 63))
    assert ok.serial == 2 ** 63

    other = run(signed, trust_root, last_serial=0, consented=2 ** 63 - 1)
    assert refusal_of(other).code == INDEX_SERIAL_JUMP


def test_consent_cannot_relax_the_rollback_floor(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys, serial=10)
    result = run(signed, trust_root, last_serial=500, consented=10)
    assert refusal_of(result).code == INDEX_ROLLBACK




def test_a_stale_index_is_degraded_and_still_installable(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    index = verified(
        run(signed, trust_root, now=DEFAULT_GENERATED_AT + timedelta(days=31))
    )
    assert index.degraded is True
    assert [item.id for item in index.items] == [ITEM_ID]


def test_a_naive_generated_at_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(
        tmp_path, keys, generated_at=datetime(2026, 9, 1, 12, 0, 0)
    )
    result = refusal_of(run(signed, trust_root))
    assert result.code == INDEX_NOT_JSON
    assert "timezone offset" in result.detail


def test_a_naive_now_is_a_caller_bug(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    with pytest.raises(ValueError, match="timezone aware"):
        run(signed, trust_root, now=datetime(2026, 9, 2, 12, 0, 0))




def test_an_item_signed_by_an_unknown_key_is_listed_untrusted(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    stranger = sign_item_versions(
        tmp_path, skill_item("stranger", PUBLISHER, DIGEST), keys.attacker
    )
    signed = good_index(
        tmp_path,
        keys,
        items=[skill_item(SKILL, PUBLISHER, DIGEST), stranger],
    )
    index = verified(run(signed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert [item.id for item in index.untrusted_items] == [f"{PUBLISHER}/stranger"]
    assert index.refused == ()


def test_a_forged_index_cannot_introduce_a_publisher(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    forged = build_signed_index(
        tmp_path,
        index_keypair=keys.index,
        publisher_keypair=keys.attacker,
        items=[skill_item(SKILL, PUBLISHER, DIGEST)],
    )
    index = verified(run(forged, trust_root))
    assert index.items == ()
    assert [item.id for item in index.untrusted_items] == [ITEM_ID]


def test_a_key_impersonating_the_pinned_id_is_not_trusted(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    item = skill_item(SKILL, PUBLISHER, DIGEST)
    sign_item_versions(tmp_path, item, keys.attacker)
    item["versions"][0]["sig"]["key_id"] = publisher_key_id(keys)
    signed = build_signed_index(
        tmp_path,
        index_keypair=keys.index,
        publisher_keypair=keys.publisher,
        items=[item],
    )
    entry = signed.document["publishers"][PUBLISHER]["keys"][0]
    entry["pub"] = impersonating_public_key(keys.publisher, keys.attacker)
    resealed = seal(tmp_path, signed.document, keys.index)

    index = verified(run(resealed, trust_root))
    assert index.items == ()
    assert index.untrusted_items == ()
    refusal = only_refused(index)
    assert refusal.code == SIGNATURE_INVALID
    assert refusal.detail.startswith("release "), refusal.detail


def test_an_honest_publishers_block_does_not_poison_anything(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    entry = signed.document["publishers"][PUBLISHER]["keys"][0]
    assert entry["pub"] == public_key_line(keys.publisher)
    assert len(verified(run(signed, trust_root)).items) == 1




@pytest.mark.parametrize(
    "field, value",
    [
        ("name", "renamed"),
        ("publisher", "eve"),
    ],
)
def test_editing_a_signed_field_breaks_the_release_statement(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot, field: str, value: str
) -> None:
    signed = good_index(tmp_path, keys)
    item = signed.document["items"][0]
    item[field] = value
    item["id"] = f"{item['publisher']}/{item['name']}"
    resealed = seal(tmp_path, signed.document, keys.index)

    item_refusal = only_refused(run(resealed, trust_root))
    assert item_refusal.code == SIGNATURE_INVALID
    assert item_refusal.detail == "release statement does not verify"


@pytest.mark.parametrize(
    "path, value",
    [
        (("digest",), "cd" * 32),
        (("src", "commit"), "b" * 40),
        (("src", "path"), "skills/eve/work"),
        (("v",), "9.9.9"),
    ],
)
def test_editing_a_signed_version_field_breaks_the_statement(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot, path: tuple, value: str
) -> None:
    signed = good_index(tmp_path, keys)
    version = signed.document["items"][0]["versions"][0]
    if len(path) == 1:
        version[path[0]] = value
    else:
        version[path[0]][path[1]] = value
    if path == ("v",):
        signed.document["items"][0]["latest"] = value
    resealed = seal(tmp_path, signed.document, keys.index)

    item_refusal = only_refused(run(resealed, trust_root))
    assert item_refusal.code == SIGNATURE_INVALID
    assert item_refusal.detail == "release statement does not verify"




def test_a_reserved_name_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(
        tmp_path, keys, items=[skill_item("security-review", PUBLISHER, DIGEST)]
    )
    item_refusal = only_refused(run(signed, trust_root))
    assert item_refusal.code == NAME_RESERVED
    assert verified(run(signed, trust_root)).items == ()


def test_an_unknown_kind_costs_one_item_and_not_the_catalog(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    from src.core.skills import kinds

    unknown = "bundle"
    assert unknown not in kinds.KINDS, (
        f"{unknown!r} is a real kind now, so this test asserts nothing. "
        f"Move it to a kind that is not in {sorted(kinds.KINDS)}."
    )

    signed = good_index(
        tmp_path,
        keys,
        items=[
            skill_item(SKILL, PUBLISHER, DIGEST),
            skill_item("dark", PUBLISHER, DIGEST, kind=unknown),
        ],
    )
    index = verified(run(signed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert len(index.refused) == 1
    assert index.refused[0].code == SIGNATURE_INVALID
    assert index.refused[0].detail.startswith(ITEM_SCHEMA_DETAIL_PREFIX)
    assert index.refused[0].item_id == f"{PUBLISHER}/dark"


def test_latest_naming_a_version_that_is_not_there_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    signed.document["items"][0]["latest"] = "9.9.9"
    resealed = seal(tmp_path, signed.document, keys.index)

    item_refusal = only_refused(run(resealed, trust_root))
    assert item_refusal.code == SIGNATURE_INVALID
    assert "latest" in item_refusal.detail


def test_an_item_that_is_not_even_an_object_costs_one_row(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    signed.document["items"].append("not an item")
    resealed = seal(tmp_path, signed.document, keys.index)

    index = verified(run(resealed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert len(index.refused) == 1
    assert index.refused[0].item_id == ""




def revoked_index(
    tmp_path: Path, keys: Keys, *, block: Dict[str, Any]
) -> SignedIndex:
    return good_index(tmp_path, keys, revocations=block)


def test_a_revoked_key_refuses_the_items_it_signed(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    entry = revocation_entry(
        tmp_path,
        kind="key",
        subject=publisher_key_id(keys),
        since="2026-09-10T00:00:00+00:00",
        keypair=keys.publisher,
    )
    signed = revoked_index(
        tmp_path, keys, block={"keys": [entry], "versions": []}
    )
    index = verified(run(signed, trust_root))
    assert index.items == ()
    assert len(index.refused) == 1
    assert index.refused[0].code == KEY_UNTRUSTED
    assert index.refused[0].detail == "key revoked"
    assert len(index.revocations) == 1


def test_a_revoked_version_refuses_that_version_only(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    entry = revocation_entry(
        tmp_path,
        kind="version",
        subject=f"{ITEM_ID}@1.0.0",
        since="2026-09-10T00:00:00+00:00",
        keypair=keys.publisher,
    )
    signed = revoked_index(
        tmp_path, keys, block={"keys": [], "versions": [entry]}
    )
    index = verified(run(signed, trust_root))
    assert index.items == ()
    assert len(index.refused) == 1
    assert index.refused[0].code == VERSION_REVOKED


def test_a_revocation_signed_by_an_unpinned_key_is_ignored_and_logged(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    entry = revocation_entry(
        tmp_path,
        kind="key",
        subject=publisher_key_id(keys),
        since="2026-09-10T00:00:00+00:00",
        keypair=keys.attacker,
    )
    signed = revoked_index(
        tmp_path, keys, block={"keys": [entry], "versions": []}
    )
    with structlog.testing.capture_logs() as captured:
        index = verified(run(signed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert index.revocations == ()
    events = [line["event"] for line in captured]
    assert "catalog_revocation_unverifiable" in events


def test_a_statement_signed_for_one_subject_cannot_revoke_another(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    entry = revocation_entry(
        tmp_path,
        kind="key",
        subject=publisher_key_id(keys),
        since="2026-09-10T00:00:00+00:00",
        keypair=keys.publisher,
    )
    entry["key_id"] = "0123456789ABCDEF"
    signed = revoked_index(
        tmp_path, keys, block={"keys": [entry], "versions": []}
    )
    index = verified(run(signed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert index.revocations == ()


def test_a_statement_that_disagrees_with_its_own_fields_is_ignored(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    entry = revocation_entry(
        tmp_path,
        kind="key",
        subject=publisher_key_id(keys),
        since="2026-09-10T00:00:00+00:00",
        keypair=keys.publisher,
    )
    entry["statement"] = revoke_statement(
        kind="key", subject="0123456789ABCDEF", since="2026-09-10T00:00:00+00:00"
    ).decode("utf-8")
    signed = revoked_index(
        tmp_path, keys, block={"keys": [entry], "versions": []}
    )
    index = verified(run(signed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert index.revocations == ()


def test_a_revocation_already_seen_applies_when_the_index_omits_it(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    sticky = frozenset(
        {
            RevocationRef(
                kind="key",
                subject=publisher_key_id(keys),
                since="2026-09-10T00:00:00+00:00",
            )
        }
    )
    signed = good_index(tmp_path, keys)
    assert signed.document["revocations"] == {"keys": [], "versions": []}
    index = verified(run(signed, trust_root, seen=sticky))
    assert index.items == ()
    assert index.refused[0].code == KEY_UNTRUSTED




@pytest.mark.parametrize("module", ["verify.py", "verify_items.py", "revocation.py"])
def test_the_verifier_holds_no_clock(module: str) -> None:
    source = (
        Path(__file__).resolve().parents[1] / "src" / "core" / "catalog" / module
    ).read_text()
    assert "datetime.now" not in source
    assert "time.time" not in source




def test_an_id_that_is_not_publisher_and_name_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    item = skill_item(SKILL, PUBLISHER, DIGEST, item_id="acme/something-else")
    signed = good_index(tmp_path, keys, items=[item])

    index = verified(run(signed, trust_root))
    assert index.items == ()
    assert index.untrusted_items == ()
    refusal = only_refused(index)
    assert refusal.code == SIGNATURE_INVALID
    assert refusal.detail.startswith(ITEM_SCHEMA_DETAIL_PREFIX)


def test_a_renamed_id_cannot_dodge_a_sticky_version_revocation(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    sticky = frozenset(
        {
            RevocationRef(
                kind="version",
                subject=f"{ITEM_ID}@1.0.0",
                since="2026-09-10T00:00:00+00:00",
            )
        }
    )
    renamed = skill_item(SKILL, PUBLISHER, DIGEST, item_id="acme/work-v2")
    signed = good_index(tmp_path, keys, items=[renamed])
    index = verified(run(signed, trust_root, seen=sticky))
    assert index.items == ()
    assert index.untrusted_items == ()

    honest = good_index(tmp_path, keys)
    still = verified(run(honest, trust_root, seen=sticky))
    assert still.items == ()
    assert only_refused(still).code == VERSION_REVOKED


def test_a_second_item_claiming_a_taken_id_is_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    first = skill_item(SKILL, PUBLISHER, DIGEST)
    second = skill_item(SKILL, PUBLISHER, DIGEST)
    sign_item_versions(tmp_path, second, keys.attacker)
    signed = build_signed_index(
        tmp_path,
        index_keypair=keys.index,
        publisher_keypair=keys.publisher,
        items=[first, second],
    )

    index = verified(run(signed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert index.untrusted_items == ()
    assert only_refused(index).code == SIGNATURE_INVALID
    assert only_refused(index).detail.startswith(ITEM_SCHEMA_DETAIL_PREFIX)


def test_two_versions_sharing_one_version_string_are_refused(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    item = skill_item(SKILL, PUBLISHER, DIGEST)
    shadow = copy.deepcopy(item["versions"][0])
    shadow["digest"] = "cd" * 32
    item["versions"].append(shadow)
    signed = good_index(tmp_path, keys, items=[item])

    index = verified(run(signed, trust_root))
    assert index.items == ()
    refusal = only_refused(index)
    assert refusal.code == SIGNATURE_INVALID
    assert refusal.detail.startswith(ITEM_SCHEMA_DETAIL_PREFIX)


def test_the_verdict_carries_the_version_it_verified(
    tmp_path: Path, keys: Keys
) -> None:
    item = sign_item_versions(
        tmp_path, skill_item(SKILL, PUBLISHER, DIGEST), keys.publisher
    )
    verdict = verify_item(
        item,
        publisher_key=parse_public_key(keys.publisher.public_key_text),
        revoked_key_ids=set(),
        revoked_versions=set(),
    )
    assert verdict.trusted is True
    assert verdict.version is not None
    assert verdict.version.v == "1.0.0"
    assert verdict.version is verdict.item.versions[0]




def test_an_impersonating_advertised_key_cannot_demote_a_genuine_item(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(tmp_path, keys)
    entry = signed.document["publishers"][PUBLISHER]["keys"][0]
    entry["pub"] = impersonating_public_key(keys.publisher, keys.attacker)
    resealed = seal(tmp_path, signed.document, keys.index)

    with structlog.testing.capture_logs() as captured:
        index = verified(run(resealed, trust_root))
    assert [item.id for item in index.items] == [ITEM_ID]
    assert index.untrusted_items == ()
    assert index.refused == ()
    assert "catalog_publisher_key_impersonated" in [
        line["event"] for line in captured
    ]




def test_a_signed_body_that_nests_too_deeply_is_not_json(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    body = ("[" * 200_000 + "]" * 200_000).encode("ascii")
    signed = SignedIndex(
        index_bytes=body,
        minisig_text=sign_bytes(tmp_path, keys.index, body, "deep"),
        document={},
    )
    assert refusal_of(run(signed, trust_root)).code == INDEX_NOT_JSON




@pytest.mark.parametrize(
    "expected,actual",
    [
        ("", ""),
        ("ab" * 32, ""),
        ("AB" * 32, "ab" * 32),
        ("ab" * 32, "AB" * 32),
        ("é" * 64, "ab" * 32),
        ("ab" * 32, "é" * 64),
        ("ab" * 31, "ab" * 31),
        ("ab" * 33, "ab" * 33),
    ],
)
def test_check_digest_refuses_anything_that_is_not_a_digest(
    expected: str, actual: str
) -> None:
    refusal = check_digest(expected, actual)
    assert refusal is not None
    assert refusal.code == DIGEST_MISMATCH
    assert refusal.detail == "malformed digest"


def test_check_digest_still_passes_a_real_pair() -> None:
    assert check_digest("ab" * 32, " " + "ab" * 32 + "\n") is None


def test_check_scripts_is_the_one_function_the_install_slice_calls(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    signed = good_index(
        tmp_path, keys, items=[skill_item(SKILL, PUBLISHER, DIGEST, scripts=3)]
    )
    listed = verified(run(signed, trust_root))
    assert [item.id for item in listed.items] == [ITEM_ID]

    refusal = check_scripts(listed.items[0].versions[0])
    assert refusal is not None
    assert refusal.code == SCRIPTS_NOT_SUPPORTED

    clean = verified(run(good_index(tmp_path, keys), trust_root))
    assert check_scripts(clean.items[0].versions[0]) is None


def test_the_two_spellings_of_the_scripts_code_agree() -> None:
    from src.core.skills.validate import SCRIPTS_NOT_SUPPORTED as EXTRACTOR

    assert SCRIPTS_NOT_SUPPORTED == EXTRACTOR




def test_a_verified_item_cannot_be_mutated(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    index = verified(run(good_index(tmp_path, keys), trust_root))
    with pytest.raises(ValidationError) as caught:
        index.items[0].name = "other"
    assert caught.value.errors()[0]["type"] == "frozen_instance"

    with pytest.raises(ValidationError):
        index.items[0].versions[0].digest = "cd" * 32




def test_a_hostile_item_id_is_bounded_and_escaped_in_the_log(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    hostile = "a" * 4096 + "\nevent=catalog_index_verified"
    signed = good_index(
        tmp_path, keys, items=[skill_item(SKILL, PUBLISHER, DIGEST, item_id=hostile)]
    )
    with structlog.testing.capture_logs() as captured:
        verified(run(signed, trust_root))
    lines = [line for line in captured if line["event"] == "catalog_item_refused"]
    assert lines, [line["event"] for line in captured]
    logged = lines[0]["item_id"]
    assert len(logged) <= 210, len(logged)
    assert "\n" not in logged


def test_a_hostile_revocation_subject_is_bounded_and_escaped_in_the_log(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot
) -> None:
    entry = revocation_entry(
        tmp_path,
        kind="key",
        subject=publisher_key_id(keys),
        since="2026-09-10T00:00:00+00:00",
        keypair=keys.publisher,
    )
    entry["key_id"] = "b" * 4096 + "\nevent=catalog_index_verified"
    signed = revoked_index(
        tmp_path, keys, block={"keys": [entry], "versions": []}
    )
    with structlog.testing.capture_logs() as captured:
        verified(run(signed, trust_root))
    lines = [
        line
        for line in captured
        if line["event"] == "catalog_revocation_unverifiable"
    ]
    assert lines, [line["event"] for line in captured]
    logged = lines[0]["subject"]
    assert len(logged) <= 210, len(logged)
    assert "\n" not in logged
