
from __future__ import annotations

import copy
import importlib.util
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from src.core.catalog.minisign import parse_public_key
from src.core.catalog.trust_root import TrustRoot
from src.core.catalog.verify import verify_index
from src.core.catalog.verify_types import KEY_UNTRUSTED, IndexEnvelope, VerifiedIndex
from src.models.catalog import PublisherEntry
from src.models.catalog_names import RESERVED_CLAIM_HANDLES
from src.models.catalog_statement import (
    parse_publisher_key_statement,
    publisher_key_statement,
)
from tests.helpers.catalog_fixture import (
    DEFAULT_GENERATED_AT,
    build_signed_index,
    public_key_line,
    revocation_entry,
    seal,
    sign_bytes,
    skill_item,
)
from tests.helpers.minisign_keys import Keypair, generate_keypair, require_minisign

DIGEST = "ab" * 32
NOW = DEFAULT_GENERATED_AT + timedelta(days=1)
ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Keys:

    index: Keypair
    root: Keypair
    k2: Keypair
    stranger: Keypair


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> Keys:
    require_minisign()
    base = tmp_path_factory.mktemp("delegation-keys")
    made = {}
    for role in ("index", "root", "k2", "stranger"):
        (base / role).mkdir()
        made[role] = generate_keypair(base / role)
    return Keys(**made)


@pytest.fixture
def trust_root(keys: Keys) -> TrustRoot:
    return TrustRoot(
        index_key=parse_public_key(keys.index.public_key_text),
        publisher_key=parse_public_key(keys.root.public_key_text),
    )


def delegation(
    tmp_path: Path, signer: Keypair, key: Keypair, *, handle: str = "alex",
    custody: str = "self",
) -> Dict[str, str]:
    parsed = parse_public_key(key.public_key_text)
    text = publisher_key_statement(
        handle=handle, key_id=parsed.key_id, pub=public_key_line(key),
        custody=custody, added="2026-10-21",
    )
    return {
        "statement": text.decode("utf-8"),
        "sig": sign_bytes(tmp_path, signer, text, "delegation"),
    }


def run(
    tmp_path: Path, keys: Keys, trust_root: TrustRoot, *,
    delegations: List[Dict[str, str]], publisher: str = "alex",
    revocations: Optional[Dict[str, Any]] = None,
) -> VerifiedIndex:
    signed = build_signed_index(
        tmp_path, index_keypair=keys.index, publisher_keypair=keys.k2,
        items=[skill_item("work", publisher, DIGEST)], revocations=revocations,
    )
    document = copy.deepcopy(signed.document)
    document["publishers"]["alex"]["delegations"] = delegations
    resealed = seal(tmp_path, document, keys.index)
    result = verify_index(
        resealed.index_bytes, resealed.minisig_text, trust_root=trust_root,
        seen_revocations=frozenset(), last_verified_serial=0, now=NOW,
    )
    assert isinstance(result, VerifiedIndex), result
    return result


def ids(entries: Any) -> List[str]:
    return [item.id for item in entries]


def test_k2_without_delegation_is_listed_untrusted(tmp_path, keys, trust_root):
    result = run(tmp_path, keys, trust_root, delegations=[])
    assert ids(result.items) == [] and ids(result.untrusted_items) == ["alex/work"]


def test_root_signed_delegation_trusts_k2(tmp_path, keys, trust_root):
    entry = delegation(tmp_path, keys.root, keys.k2)
    result = run(tmp_path, keys, trust_root, delegations=[entry])
    assert ids(result.items) == ["alex/work"] and result.untrusted_items == ()


def test_stranger_signed_delegation_is_ignored(tmp_path, keys, trust_root):
    entry = delegation(tmp_path, keys.stranger, keys.k2)
    result = run(tmp_path, keys, trust_root, delegations=[entry])
    assert ids(result.items) == [] and ids(result.untrusted_items) == ["alex/work"]


def test_delegation_for_another_handle_does_not_cover_this_one(tmp_path, keys, trust_root):
    entry = delegation(tmp_path, keys.root, keys.k2, handle="bob")
    result = run(tmp_path, keys, trust_root, delegations=[entry])
    assert ids(result.items) == []


def test_catalog_star_covers_ordinary_handles_only(tmp_path, keys, trust_root):
    star = delegation(tmp_path, keys.root, keys.k2, handle="*", custody="catalog")
    assert ids(run(tmp_path, keys, trust_root, delegations=[star]).items) == ["alex/work"]
    for reserved in ("carnivore", "nyedis", "external", "bundled", "claude"):
        result = run(tmp_path, keys, trust_root, delegations=[star], publisher=reserved)
        assert result.items == (), reserved
        assert ids(result.untrusted_items) == [f"{reserved}/work"], reserved


def test_kms_root_delegation_covers_first_party_handles_only(tmp_path, keys, trust_root):
    kms = delegation(tmp_path, keys.root, keys.k2, handle="carnivore", custody="kms")
    result = run(tmp_path, keys, trust_root, delegations=[kms], publisher="carnivore")
    assert ids(result.items) == ["carnivore/work"] and result.untrusted_items == ()
    catalog = delegation(tmp_path, keys.root, keys.k2, handle="carnivore", custody="catalog")
    result = run(tmp_path, keys, trust_root, delegations=[catalog], publisher="carnivore")
    assert result.items == () and ids(result.untrusted_items) == ["carnivore/work"]
    stranger = delegation(tmp_path, keys.stranger, keys.k2, handle="carnivore", custody="kms")
    result = run(tmp_path, keys, trust_root, delegations=[stranger], publisher="carnivore")
    assert result.items == () and ids(result.untrusted_items) == ["carnivore/work"]
    with pytest.raises(ValueError):
        delegation(tmp_path, keys.root, keys.k2, handle="alex", custody="kms")


def test_revoked_delegated_key_is_refused(tmp_path, keys, trust_root):
    entry = delegation(tmp_path, keys.root, keys.k2)
    k2_id = parse_public_key(keys.k2.public_key_text).key_id
    revoked = {"keys": [revocation_entry(
        tmp_path, kind="key", subject=k2_id, since="2026-10-22", keypair=keys.root,
    )], "versions": []}
    result = run(tmp_path, keys, trust_root, delegations=[entry], revocations=revoked)
    assert result.items == () and result.untrusted_items == ()
    assert [r.code for r in result.refused] == [KEY_UNTRUSTED]


def test_statement_claiming_another_keys_id_is_ignored(tmp_path, keys, trust_root):
    k2_id = parse_public_key(keys.k2.public_key_text).key_id
    text = publisher_key_statement(
        handle="alex", key_id=k2_id, pub=public_key_line(keys.stranger),
        custody="self", added="2026-10-21",
    )
    entry = {"statement": text.decode(), "sig": sign_bytes(tmp_path, keys.root, text)}
    assert ids(run(tmp_path, keys, trust_root, delegations=[entry]).items) == []


def test_malformed_entries_cost_only_themselves(tmp_path, keys, trust_root):
    good = delegation(tmp_path, keys.root, keys.k2)
    junk: List[Any] = [None, "x", {"statement": 1}, {"statement": "carnivore-publisher-key-v1\n", "sig": "s"}]
    result = run(tmp_path, keys, trust_root, delegations=[*junk, good])
    assert ids(result.items) == ["alex/work"]


def test_statement_is_six_strict_lines():
    kwargs = dict(handle="alex", key_id="5F522AB084F4E697", pub="RWRfUiqwhPTml", custody="self", added="2026-10-21")
    text = publisher_key_statement(**kwargs).decode()
    assert text.count("\n") == 6 and text.startswith("carnivore-publisher-key-v1\n")
    assert parse_publisher_key_statement(text).handle == "alex"
    for bad in (text + "\n", text.replace("\n", "\r\n"), text[:-1], "x" + text, text.replace("self", "other")):
        with pytest.raises(ValueError):
            parse_publisher_key_statement(bad)
    with pytest.raises(ValueError):
        publisher_key_statement(**{**kwargs, "handle": "*"})
    with pytest.raises(ValueError):
        publisher_key_statement(**{**kwargs, "added": "2026-13-40"})


def test_old_envelope_shape_ignores_delegations_and_reserved_list_matches_hosted(monkeypatch):
    assert PublisherEntry.model_validate({"github_login": "a", "future_field": [1]}).delegations == []
    assert IndexEnvelope.model_validate(
        {"schema": "carnivore.catalog.index/1", "serial": 1, "generated_at": "x",
         "publishers": {"a": {"github_login": "a", "delegations": [{"x": 1}], "new": 1}}, "items": []}
    ).publishers["a"].delegations == [{"x": 1}]
    path = ROOT / "hosted" / "catalog" / "api" / "validate_upload.py"
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location("hosted_validate_upload", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert RESERVED_CLAIM_HANDLES == module.RESERVED_CLAIM_HANDLES
