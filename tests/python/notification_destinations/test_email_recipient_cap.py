
from __future__ import annotations

from src.core.notifications import kind_specs
from src.core.notifications.destinations import validate
from src.core.notifications.kinds import smtp_transport


def _recipients_field() -> kind_specs.FieldSpec:
    spec = kind_specs.get_kind(kind_specs.KIND_EMAIL)
    return next(f for f in spec.secret_fields if f.name == "recipients")


def test_the_save_time_cap_is_the_transport_cap():
    field = _recipients_field()
    assert field.max_items == smtp_transport.MAX_RECIPIENTS
    ok = ",".join(f"a{i}@example.com" for i in range(smtp_transport.MAX_RECIPIENTS))
    too_many = ok + ",extra@example.com"
    assert validate._list(ok, field)[1] is None
    assert validate._list(too_many, field)[1] == validate.TOO_LONG
