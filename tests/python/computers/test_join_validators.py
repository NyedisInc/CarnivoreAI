
from __future__ import annotations

from pathlib import Path

from src.core.computers import door, join_helper
from src.core.computers.join_identity import lan_address_ok

ROOT = Path(__file__).resolve().parents[3]


def test_helper_line_pins_https_and_tls() -> None:
    text = (ROOT / "web/src/lib/first-run/join-api.ts").read_text()
    line = next(l for l in text.splitlines() if l.startswith("export const HELPER_LINE"))
    assert "--proto" in line and "=https" in line and "--tlsv1.2" in line


def test_validators_reject_trailing_newline() -> None:
    assert lan_address_ok("x.local") and not lan_address_ok("x.local\n")
    assert door.RELAY_NAME.fullmatch("relay-0123456789abcdef.sock") and not door.RELAY_NAME.fullmatch("relay-0123456789abcdef.sock\n")
    assert door.RELAY_ADDRESS.fullmatch("10.0.0.5") and not door.RELAY_ADDRESS.fullmatch("10.0.0.5\n")
    assert door.RELAY_FID.fullmatch("a" * 16) and not door.RELAY_FID.fullmatch("a" * 16 + "\n")
    assert join_helper._DOOR_NAME.fullmatch("door-0123abcd.sock") and not join_helper._DOOR_NAME.fullmatch("door-0123abcd.sock\n")


def test_validator_call_sites_use_fullmatch() -> None:
    for rel, names in (("door.py", ("RELAY_NAME", "RELAY_ADDRESS", "RELAY_FID")), ("join_helper.py", ("_DOOR_NAME",)), ("join_identity.py", ("_LOCAL_NAME",))):
        src = (ROOT / "src/core/computers" / rel).read_text()
        for name in names:
            assert f"{name}.match(" not in src, (rel, name)
