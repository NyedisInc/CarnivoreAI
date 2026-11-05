
from __future__ import annotations

from typing import Optional

import pytest
from pydantic import BaseModel, PydanticUserError, field_validator

from src.core.ui_preferences import UiPreferenceValues


def test_every_field_validator_names_a_field_of_the_model() -> None:
    validators = UiPreferenceValues.__pydantic_decorators__.field_validators
    assert len(validators) >= 30
    for name, decorator in validators.items():
        missing = [f for f in decorator.info.fields if f not in UiPreferenceValues.model_fields]
        assert not missing, f"{name} guards unknown field(s) {missing}"


def test_the_guard_can_go_red_a_misnamed_validator_is_refused_at_class_creation() -> None:

    def check(value: Optional[str]) -> Optional[str]:
        return value

    with pytest.raises(PydanticUserError):
        class Broken(BaseModel):  # noqa: F841
            real: Optional[str] = None
            _typo = field_validator("reel")(check)
