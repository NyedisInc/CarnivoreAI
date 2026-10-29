import pytest

from src.core.app_alerts.store import AlertInputError, AlertSpec, validate


def _spec(href: str) -> AlertSpec:
    return AlertSpec(key="k", source="s", severity="info", title_key="app_alert.t",
                     actions=[{"id": "open", "label_key": "app_alert.open", "href": href}])


def test_fragment_accepted() -> None:
    validate(_spec("#automations/run/x"))


@pytest.mark.parametrize("href", ["javascript:alert(1)", "https://evil", "//evil", ""])
def test_non_fragment_refused(href: str) -> None:
    with pytest.raises(AlertInputError):
        validate(_spec(href))
