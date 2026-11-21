
from __future__ import annotations

import pytest

from src.core import product_identity


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in product_identity.env_names("TEST_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_unset_is_off() -> None:
    assert product_identity.test_mode_enabled() is False


@pytest.mark.parametrize("name", ["CARNIVORE_TEST_MODE", "CLOUDE_TEST_MODE", "CLOUDECODE_TEST_MODE"])
def test_every_spelling_turns_it_on(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(name, "1")
    assert product_identity.test_mode_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_a_falsey_value_is_off_not_on(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDE_TEST_MODE", value)
    assert product_identity.test_mode_enabled() is False


def test_the_guarded_call_sites_use_the_one_helper() -> None:
    from pathlib import Path

    src = Path(product_identity.__file__).resolve().parents[1]
    hand_rolled = []
    for path in src.rglob("*.py"):
        if path.name in {"product_identity.py", "poller.py", "poller_core.py", "refresh_poke.py", "federation_pack_ledger_routes.py"}:
            continue
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if "environ" in line and "TEST_MODE" in line and not line.lstrip().startswith("#"):
                hand_rolled.append(f"{path.relative_to(src)}:{number}")
    assert hand_rolled == []
