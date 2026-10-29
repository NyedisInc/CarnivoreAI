"""Request-model contracts: one-line answers, bounded terminal size, and honest schema text (wave G, M17)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.adopt import AdoptSessionRequest
from src.models.config_settings import ConfigSettingsUpdateRequest
from src.models.dialogs import AnswerChoice
from src.models.session_requests import CreateSessionRequest
from src.models.sessions import SessionInfo


@pytest.mark.parametrize("text", ["a\u009bb", "a\u0085b", "a b", "a b", "a\nb", "a\x7fb"])
def test_single_answer_other_refuses_c1_and_separators(text: str) -> None:
    with pytest.raises(ValidationError):
        AnswerChoice(other=text)


@pytest.mark.parametrize("field", ["option", "options"])
def test_single_answer_labels_refuse_control_text(field: str) -> None:
    bad = "x\u009by"
    with pytest.raises(ValidationError):
        AnswerChoice(**{field: bad if field == "option" else [bad]})


def test_single_answer_plain_text_still_passes() -> None:
    assert AnswerChoice(other="hello world").other == "hello world"
    assert AnswerChoice(option="Yes, and don't ask again").option
    assert AnswerChoice(options=["A", "B"]).options == ["A", "B"]


@pytest.mark.parametrize("cls,extra", [(CreateSessionRequest, {"working_dir": "/tmp"}), (AdoptSessionRequest, {"session_name": "x"})])
@pytest.mark.parametrize("bad", [{"cols": -5}, {"cols": 100000}, {"rows": 0}, {"rows": 100000}])
def test_terminal_size_is_bounded_on_create_and_adopt(cls, extra, bad) -> None:
    with pytest.raises(ValidationError):
        cls(**extra, **bad)


def test_terminal_size_in_range_passes() -> None:
    assert CreateSessionRequest(working_dir="/tmp", cols=163, rows=46).cols == 163


def test_settings_docs_name_only_the_real_blocks() -> None:
    from src.models import config_settings

    assert "four sub-blocks" not in (config_settings.__doc__ or "")
    assert "``notifications``" not in (ConfigSettingsUpdateRequest.__doc__ or "")
    assert set(ConfigSettingsUpdateRequest.model_fields) == {"workspace", "server_prefs"}


def test_status_source_description_matches_the_vocabulary() -> None:
    desc = SessionInfo.model_fields["status_source"].description or ""
    assert "hook" not in desc
    for name in ("registry", "pane", "transcript", "seed_row", "tmux", "none"):
        assert name in desc
