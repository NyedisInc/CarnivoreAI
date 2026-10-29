
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.catalog.minisign import parse_public_key, parse_signature, verify
from src.models.catalog import (
    PUBLISHER_RE,
    RESERVED_SKILL_NAMES,
    SKILL_NAME_RE,
    VERSION_RE,
    CatalogItem,
    IndexDocument,
    ItemVersion,
    ReviewBlock,
    RevokedVersion,
    _match_or_raise,
    is_reserved_name,
)
from src.models.catalog_statement import release_statement
from tests.helpers.minisign_keys import generate_keypair, sign_file

COMMIT = "a" * 40
DIGEST = "b" * 64


def _version(**overrides) -> dict:
    version = {
        "v": "1.2.3",
        "src": {
            "repo": "carnivore-ai/catalog",
            "path": "skills/carnivore/work",
            "commit": COMMIT,
        },
        "digest": DIGEST,
        "size": 4096,
        "files": 3,
        "scripts": 0,
        "published_at": "2026-09-15T00:00:00Z",
        "sig": {
            "key_id": "5F522AB084F4E697",
            "sig": "c2ln",
            "tc": "serial:7",
            "gsig": "Z3NpZw==",
        },
    }
    version.update(overrides)
    return version


def _item(**overrides) -> dict:
    item = {
        "id": "carnivore/work",
        "kind": "skill",
        "name": "work",
        "publisher": "carnivore",
        "latest": "1.2.3",
        "card": {"title": "Work", "brief": "How work is claimed"},
        "fm": {"description": "How work is claimed in this repo"},
        "versions": [_version()],
    }
    item.update(overrides)
    return item


def _index(**overrides) -> dict:
    document = {
        "schema": "carnivore.catalog.index/1",
        "serial": 7,
        "generated_at": "2026-09-15T00:00:00Z",
        "publishers": {
            "carnivore": {
                "github_login": "Example-owner",
                "keys": [{
                    "key_id": "5F522AB084F4E697",
                    "alg": "Ed",
                    "pub": "RWSX5vSEsCpSX057",
                    "added": "2026-09-15T00:00:00Z",
                    "status": "active",
                }],
            },
        },
        "revocations": {"keys": [], "versions": []},
        "items": [_item()],
    }
    document.update(overrides)
    return document


def test_a_minimum_index_parses():
    parsed = IndexDocument(**_index())
    assert parsed.schema_version == "carnivore.catalog.index/1"
    assert parsed.serial == 7
    assert parsed.items[0].name == "work"
    assert parsed.items[0].versions[0].src.commit == COMMIT


@pytest.mark.parametrize(
    "name",
    ["work", "a", "a" * 64, "skill.v2", "my_skill", "my-skill", "x1"],
)
def test_a_valid_skill_name_is_accepted(name):
    assert SKILL_NAME_RE.fullmatch(name)
    assert CatalogItem(**_item(name=name)).name == name


@pytest.mark.parametrize(
    "name,why",
    [
        (".hidden", "a leading dot shadows a harness's own .system folder"),
        ("..", "the parent directory"),
        ("../etc", "traversal"),
        ("a/b", "a separator escapes the install directory"),
        ("Work", "uppercase"),
        ("a" * 65, "65 characters, one over"),
        ("", "empty"),
        ("-lead", "a leading hyphen is not a letter or digit"),
        ("_lead", "a leading underscore is not a letter or digit"),
        ("has space", "a space"),
        ("null\x00byte", "a NUL"),
        ("sme.", "the squat: a flat namespace reads a trailing dot as a key"),
        ("work.", "a trailing dot on any name, not only the one measured"),
        ("a-", "a trailing hyphen"),
        ("a_", "a trailing underscore"),
    ],
)
def test_an_invalid_skill_name_is_refused(name, why):
    assert not SKILL_NAME_RE.fullmatch(name), why
    with pytest.raises(ValidationError):
        CatalogItem(**_item(name=name))


@pytest.mark.parametrize("publisher", ["carnivore", "a", "a-b", "a" * 39, "a-b-c9"])
def test_a_valid_publisher_is_accepted(publisher):
    assert PUBLISHER_RE.fullmatch(publisher)
    assert CatalogItem(**_item(publisher=publisher)).publisher == publisher


@pytest.mark.parametrize(
    "publisher,why",
    [
        ("a" * 40, "40 characters, one over GitHub's own limit"),
        ("-", "a bare hyphen is a leading hyphen and a trailing one"),
        ("-a", "a leading hyphen reads as an option flag to any CLI"),
        ("a-", "a trailing hyphen; GitHub refuses it too"),
        ("Carnivore", "uppercase"),
        ("carni.vore", "a dot"),
        ("carni_vore", "an underscore"),
        ("a/b", "a separator"),
        (".carnivore", "a leading dot"),
        ("", "empty"),
    ],
)
def test_an_invalid_publisher_is_refused(publisher, why):
    assert not PUBLISHER_RE.fullmatch(publisher), why
    with pytest.raises(ValidationError):
        CatalogItem(**_item(publisher=publisher))


def test_a_publisher_handle_in_the_publishers_map_is_validated_too():
    document = _index()
    document["publishers"] = {
        "../escape": document["publishers"]["carnivore"],
    }
    with pytest.raises(ValidationError):
        IndexDocument(**document)


def test_the_reserved_list_holds_both_measured_sources():
    assert "skill-installer" in RESERVED_SKILL_NAMES
    assert "security-review" in RESERVED_SKILL_NAMES
    assert is_reserved_name("init")
    assert is_reserved_name("  Security-Review  ")
    assert not is_reserved_name("work")
    for name in RESERVED_SKILL_NAMES:
        assert SKILL_NAME_RE.fullmatch(name), (
            f"{name} could never be published anyway, so reserving it is "
            "either a typo or a name shape this list does not understand"
        )


@pytest.mark.parametrize(
    "kind",
    ["network", "file_delete", "credential_access", "shell_exec",
     "obfuscation", "privilege", "other"],
)
def test_every_declared_warning_kind_is_accepted(kind):
    review = ReviewBlock(
        status="reviewed",
        summary="reads one file",
        warnings=[{"kind": kind, "detail": "reaches the network"}],
    )
    assert review.warnings[0].kind == kind


def test_an_unrecognised_warning_kind_parses_so_the_item_stays_listed():
    review = ReviewBlock(
        status="reviewed",
        warnings=[{"kind": "mining", "detail": "x"}],
    )
    assert review.warnings[0].kind == "mining"


def test_a_warning_kind_of_the_wrong_shape_is_refused():
    with pytest.raises(ValidationError):
        ReviewBlock(
            status="reviewed",
            warnings=[{"kind": "Mining!", "detail": "x"}],
        )


def test_an_unavailable_review_is_a_value_and_an_absent_one_is_not():
    reviewed = ItemVersion(**_version(review={
        "status": "reviewed", "summary": "no findings", "warnings": [],
    }))
    unavailable = ItemVersion(**_version(review={"status": "unavailable"}))
    absent = ItemVersion(**_version())

    assert reviewed.review.status == "reviewed"
    assert reviewed.review.warnings == []
    assert unavailable.review is not None
    assert unavailable.review.status == "unavailable"
    assert unavailable.review.warnings is None
    assert absent.review is None
    assert unavailable.review != absent.review


def test_a_review_status_outside_the_two_is_refused():
    with pytest.raises(ValidationError):
        ReviewBlock(status="pending")


def test_an_unknown_top_level_field_is_ignored_not_refused():
    parsed = IndexDocument(**_index(rating_snapshot={"stars": 5}, kinds=["x"]))
    assert parsed.serial == 7
    assert not hasattr(parsed, "rating_snapshot")


def test_a_kind_the_client_does_not_know_is_refused():
    from src.core.skills import kinds

    unknown = "bundle"
    assert unknown not in kinds.KINDS, (
        f"{unknown!r} is a real kind now, so this test asserts nothing. "
        f"Move it to a kind that is not in {sorted(kinds.KINDS)}."
    )

    with pytest.raises(ValidationError):
        CatalogItem(**_item(kind=unknown))


@pytest.mark.parametrize(
    "commit",
    ["a" * 39, "a" * 41, "A" * 40, "g" * 40, ""],
    ids=["short", "long", "uppercase", "not-hex", "empty"],
)
def test_a_commit_that_is_not_40_lowercase_hex_is_refused(commit):
    with pytest.raises(ValidationError):
        ItemVersion(**_version(src={
            "repo": "carnivore-ai/catalog",
            "path": "skills/carnivore/work",
            "commit": commit,
        }))


@pytest.mark.parametrize(
    "digest",
    ["b" * 63, "b" * 65, "B" * 64, "z" * 64],
    ids=["short", "long", "uppercase", "not-hex"],
)
def test_a_digest_that_is_not_64_lowercase_hex_is_refused(digest):
    with pytest.raises(ValidationError):
        ItemVersion(**_version(digest=digest))


def test_latest_must_name_a_version_the_item_actually_carries():
    with pytest.raises(ValidationError):
        CatalogItem(**_item(latest="9.9.9"))


def test_an_item_with_no_versions_is_refused():
    with pytest.raises(ValidationError):
        CatalogItem(**_item(versions=[], latest="1.2.3"))


def test_a_script_bearing_version_still_parses_and_is_visible():
    assert ItemVersion(**_version(scripts=2)).scripts == 2
    assert ItemVersion(**_version(scripts=True)).scripts == 1


def test_the_release_statement_is_exactly_these_bytes():
    statement = release_statement(
        kind="skill",
        publisher="carnivore",
        name="work",
        version="1.2.3",
        repo="carnivore-ai/catalog",
        path="skills/carnivore/work",
        commit=COMMIT,
        digest=DIGEST,
    )
    assert statement == (
        b"carnivore-release-v1\n"
        b"skill\n"
        b"carnivore\n"
        b"work\n"
        b"1.2.3\n"
        b"carnivore-ai/catalog\n"
        b"skills/carnivore/work\n"
        + b"a" * 40 + b"\n"
        + b"b" * 64 + b"\n"
    )
    assert statement.count(b"\n") == 9
    assert b"\r" not in statement
    assert not statement.endswith(b"\n\n")


@pytest.mark.parametrize(
    "field,value,why",
    [
        ("repo", "a\nb", "a newline forges a different statement"),
        ("path", "a\rb", "a CR does the same on a lenient reader"),
        ("version", "", "empty"),
        ("publisher", "Carnivore", "publisher shape"),
        ("name", "../escape", "name shape"),
    ],
)
def test_the_release_statement_refuses_a_field_that_could_forge_one(
    field, value, why,
):
    fields = {
        "kind": "skill",
        "publisher": "carnivore",
        "name": "work",
        "version": "1.2.3",
        "repo": "carnivore-ai/catalog",
        "path": "skills/carnivore/work",
        "commit": COMMIT,
        "digest": DIGEST,
    }
    fields[field] = value
    with pytest.raises(ValueError):
        release_statement(**fields)


def test_a_real_signature_over_a_release_statement_verifies(tmp_path: Path):
    statement = release_statement(
        kind="skill",
        publisher="carnivore",
        name="work",
        version="1.2.3",
        repo="carnivore-ai/catalog",
        path="skills/carnivore/work",
        commit=COMMIT,
        digest=DIGEST,
    )
    keypair = generate_keypair(tmp_path)
    target = tmp_path / "release.txt"
    target.write_bytes(statement)
    signature = parse_signature(sign_file(keypair, target, "release:1.2.3"))
    public_key = parse_public_key(keypair.public_key_text)

    assert verify(
        statement, signature, public_key, expect_prehashed=True,
    ) is True
    assert verify(
        statement + b"x", signature, public_key, expect_prehashed=True,
    ) is False


OLD_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


@pytest.mark.parametrize("name", ["sme.", "work.", "a-", "a_"])
def test_the_old_name_pattern_accepted_the_squat(name):
    assert OLD_SKILL_NAME_RE.fullmatch(name), (
        f"negative control failed: the old pattern did not accept {name!r}"
    )
    assert not SKILL_NAME_RE.fullmatch(name)


def test_the_name_length_bound_and_leading_rule_did_not_move():
    assert SKILL_NAME_RE.fullmatch("a" * 64)
    assert not SKILL_NAME_RE.fullmatch("a" * 65)
    for name in (".hidden", "..", "-lead", "_lead"):
        assert not SKILL_NAME_RE.fullmatch(name)


@pytest.mark.parametrize(
    "version",
    ["1.0.0", "1", "1.2", "1.2.3.4", "0.0.1", "10.20.30", "1.0.0-rc.1",
     "1.0.0-beta2", "2.0.0-alpha-3"],
)
def test_a_reasonable_version_is_accepted(version):
    assert VERSION_RE.fullmatch(version)
    assert ItemVersion(**_version(v=version)).v == version


@pytest.mark.parametrize(
    "version,why",
    [
        ("../../../etc", "traversal; the publishing side reads a file stem"),
        ("9" * 400, "four hundred digits rendered raw in the CLI"),
        ("$(id)", "a shell substitution"),
        ("   ", "whitespace only"),
        ("1.0.0@evil", "an @ breaks the revocation subject's own parse"),
        ("1.0.0 ", "a trailing space is a different version and does not look it"),
        ("v1.0.0", "a leading v; two spellings of one version is two rows"),
        ("1.0.0/x", "a separator"),
        ("1.0.0-", "a trailing hyphen on the prerelease"),
        ("\x1b[31m1.0.0", "an ANSI escape"),
    ],
)
def test_an_unreasonable_version_is_refused(version, why):
    assert len(version) >= 1, "the old field bound was min_length=1"
    assert not VERSION_RE.fullmatch(version), why
    with pytest.raises(ValidationError):
        ItemVersion(**_version(v=version))


@pytest.mark.parametrize(
    "value,pattern",
    [("sme\n", SKILL_NAME_RE), ("1.0.0\n", VERSION_RE)],
)
def test_a_trailing_newline_is_refused_by_fullmatch_not_match(value, pattern):
    assert pattern.match(value), (
        f"negative control failed: re.match did not accept {value!r}"
    )
    assert not pattern.fullmatch(value)
    with pytest.raises(ValueError):
        _match_or_raise(value, pattern, "value")


def test_a_revoked_version_is_held_to_the_same_shape():
    good = {
        "item": "example-owner/sme", "version": "1.0.0", "since": "2026-09-15",
        "statement": "carnivore-revoke-v1", "sig": "x",
    }
    assert RevokedVersion(**good).version == "1.0.0"
    with pytest.raises(ValidationError):
        RevokedVersion(**{**good, "version": "1.0.0@evil"})


def test_the_release_statement_refuses_both_shapes():
    fields = dict(
        kind="skill", publisher="example-owner", name="sme", version="1.0.0",
        repo="Example-owner/CarnivoreAI-Skills", path="skills/example-owner/sme",
        commit=COMMIT, digest=DIGEST,
    )
    assert release_statement(**fields).startswith(b"carnivore-release-v1\n")
    with pytest.raises(ValueError):
        release_statement(**{**fields, "name": "sme."})
    with pytest.raises(ValueError):
        release_statement(**{**fields, "version": "../../../etc"})
