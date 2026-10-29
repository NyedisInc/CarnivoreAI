
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from src.core.skills.digest import (
    DIGEST_DOMAIN,
    DigestEntry,
    digest_entries,
    render_entries,
)

VECTOR_FILE = Path(__file__).resolve().parents[1] / "digest_vectors.json"


def load_vectors() -> list:
    assert VECTOR_FILE.is_file(), (
        f"{VECTOR_FILE} is missing. it is shared with the catalog build job "
        f"and is what stops the two digest implementations from drifting."
    )
    document = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    vectors = document["vectors"]
    assert vectors, "the vector file carries no vectors"
    return vectors


def test_the_domain_prefix_is_the_one_in_the_file() -> None:
    document = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    assert document["domain"].encode("utf-8") == DIGEST_DOMAIN


@pytest.mark.parametrize("vector", load_vectors(), ids=lambda v: v["name"])
def test_vector_render_and_digest(vector: dict) -> None:
    entries = [
        DigestEntry(relpath=e["relpath"], mode=e["mode"], sha256=e["sha256"])
        for e in vector["entries"]
    ]
    assert render_entries(entries) == base64.b64decode(vector["render_b64"]), (
        f"{vector['name']}: the canonical rendering changed. the build job in "
        f"NyedisInc/CarnivoreAI-Catalog renders these bytes too."
    )
    assert digest_entries(entries) == vector["digest"], (
        f"{vector['name']}: the digest changed. every signature ever made over "
        f"a digest is now wrong."
    )


def test_the_five_named_shapes_are_all_present() -> None:
    names = {vector["name"] for vector in load_vectors()}
    assert names == {
        "empty-folder", "one-file", "exec-bit", "utf8-ordering", "dotted-names",
    }


def test_the_empty_folder_is_the_domain_alone() -> None:
    import hashlib

    empty = next(v for v in load_vectors() if v["name"] == "empty-folder")
    assert empty["digest"] == hashlib.sha256(DIGEST_DOMAIN).hexdigest()
    assert digest_entries([]) == empty["digest"]
