import pytest

from scripts.widgets.harness import junk_findings


@pytest.mark.parametrize("text", [
    "cloude_billing-api asks to act", "state unknown", "value undefined", "ses_abc123 is open",
    "/Users/someone/work", "host 10.0.0.5", "mini.local", "a" * 40, "[object Object]",
])
def test_junk_is_flagged(text: str) -> None:
    assert junk_findings(text), text


@pytest.mark.parametrize("text", [
    "billing-api asks to act on infra-tools", "/work/billing-api", "retry 5 times over about an hour", "nothing waiting",
])
def test_made_up_copy_passes(text: str) -> None:
    assert junk_findings(text) == []
