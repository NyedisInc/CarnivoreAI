from __future__ import annotations

import pytest

from src.core.session_token_usage.model_table import MODEL_TABLE, readable_model_name
from src.core.stats import events, queries


@pytest.mark.parametrize("model, name", [
    ("claude-opus-5-5", "Opus 5.5"),
    ("claude-sonnet-5-5", "Sonnet 5.5"),
    ("claude-haiku-4-5", "Haiku 4.5"),
    ("claude-fable-5-1", "Fable 5.1"),
    ("claude-haiku-4-5-20251001", "Haiku 4.5"),
    ("gpt-6-sol", "GPT-6 Sol"),
    ("gpt-5-codex", "GPT-5 Codex"),
    ("claude-opus-6-1", "Opus 6.1"),
    ("claude-sonnet-7-2-20270101", "Sonnet 7.2"),
    ("gpt-7-terra", "GPT-7 Terra"),
    ("gpt-5.6-terra", "GPT-5.6 Terra"),
    ("mistral-large-2", "Mistral Large 2"),
    ("", ""),
    (None, ""),
])
def test_readable_model_name(model, name):
    assert readable_model_name(model) == name


def test_every_table_row_answers_its_own_product_name():
    for model, facts in MODEL_TABLE.items():
        assert readable_model_name(model) == (facts.display_name or readable_model_name(model))
        assert "-" not in readable_model_name(model).replace("GPT-", "")


def test_a_model_dimension_keeps_its_id_as_key_and_filter_but_labels_it_by_name():
    assert queries._public_dimension("model", "claude-opus-5-5") == ("claude-opus-5-5", "Opus 5.5", "claude-opus-5-5")
    assert queries._public_dimension("model", "claude-opus-9-9") == ("claude-opus-9-9", "Opus 9.9", "claude-opus-9-9")
    assert queries._public_dimension("agent_kind", "subagent")[1] == "subagent"


def test_the_event_rail_labels_a_new_model_by_name_and_leaves_other_subjects_alone():
    assert events._subject_label("model_first_seen", "gpt-6-sol") == "GPT-6 Sol"
    assert events._subject_label("account_switched", "gpt-6-sol") == "gpt-6-sol"
