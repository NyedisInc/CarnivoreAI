
from __future__ import annotations

from types import SimpleNamespace

from src.core.attention.evidence import EvidenceIdentity, observed_conversation_uuid


def test_named_fields_and_tuple_compat() -> None:
    ident = EvidenceIdentity("cloude", "cloude_a", 17, 4242, "uuid-1")
    assert ident.conversation_uuid == "uuid-1" and ident[4] == "uuid-1"
    assert ident.instance == ("cloude", "cloude_a", 17, 4242)


def test_observed_uuid_reads_plain_tuple_and_absent() -> None:
    assert observed_conversation_uuid(SimpleNamespace(identity=("s", "n", 1, 2, "u"))) == "u"
    assert observed_conversation_uuid(SimpleNamespace(identity=None)) is None
    assert observed_conversation_uuid(SimpleNamespace()) is None
    assert EvidenceIdentity.coerce(("s", "n")).conversation_uuid is None
