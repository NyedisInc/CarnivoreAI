from __future__ import annotations

import os
import re
import shlex
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_modelid_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_modelid_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

from src.models import (
    MODEL_ID_PATTERN,
    is_valid_model_id,
    describe_model_id_rejection,
    CreateSessionRequest,
    AddProviderModelRequest,
)

_OLD_MODEL_ID_PATTERN = r"^(?!-)[A-Za-z0-9._~/-]{1,120}$"
_OLD_MODEL_ID_RE = re.compile(_OLD_MODEL_ID_PATTERN)


VARIANT_SUFFIXES = [":free", ":nitro", ":online", ":extended", ":beta"]
REALISTIC_FULL_ID = "nvidia/nemotron-3-nano-30b-a3b:free"


class TestAcceptedVariantSuffixes:

    @pytest.mark.parametrize("suffix", VARIANT_SUFFIXES)
    def test_variant_suffix_accepted(self, suffix: str) -> None:
        model_id = f"some-vendor/some-model{suffix}"
        assert is_valid_model_id(model_id), model_id

    def test_realistic_full_id_round_trips(self) -> None:
        assert is_valid_model_id(REALISTIC_FULL_ID)
        req = CreateSessionRequest(model=REALISTIC_FULL_ID)
        assert req.model == REALISTIC_FULL_ID


class TestRedAgainstOldPattern:

    @pytest.mark.parametrize("suffix", VARIANT_SUFFIXES)
    def test_variant_suffix_rejected_by_old_pattern(self, suffix: str) -> None:
        model_id = f"some-vendor/some-model{suffix}"
        assert not _OLD_MODEL_ID_RE.fullmatch(model_id), model_id

    def test_realistic_full_id_rejected_by_old_pattern(self) -> None:
        assert not _OLD_MODEL_ID_RE.fullmatch(REALISTIC_FULL_ID)


class TestStillRejected:

    @pytest.mark.parametrize(
        "bad_id",
        [
            "-x",
            "--continue",
            ":free",
            "vendor/model:",
            "vendor:model:free",
            "a::b",
            "a b",
            "a\tb",
            "a\nb",
            "'x",
            '"x',
            "`x`",
            "$(id)",
            "${PATH}",
            "a;b",
            "a|b",
            "a&b",
            "..",
            "a/../b",
            "a" * 121,
            "",
            " ",
        ],
    )
    def test_rejected(self, bad_id: str) -> None:
        assert not is_valid_model_id(bad_id), bad_id

    def test_length_cap_boundary(self) -> None:
        assert is_valid_model_id("a" * 120)
        assert not is_valid_model_id("a" * 121)


class TestRejectionReasonsDistinguishable:

    def test_leading_hyphen_reason_is_specific(self) -> None:
        reason = describe_model_id_rejection("-x")
        assert "start with '-'" in reason
        assert "flag" in reason

    def test_leading_colon_reason_is_specific(self) -> None:
        reason = describe_model_id_rejection(":free")
        assert "start or end with ':'" in reason

    def test_trailing_colon_reason_is_specific(self) -> None:
        reason = describe_model_id_rejection("vendor/model:")
        assert "start or end with ':'" in reason

    def test_double_colon_reason_is_specific(self) -> None:
        reason = describe_model_id_rejection("a::b")
        assert "one ':'" in reason

    def test_path_traversal_reason_is_specific(self) -> None:
        reason = describe_model_id_rejection("a/../b")
        assert "'..'" in reason

    def test_metacharacter_reason_names_the_character(self) -> None:
        reason = describe_model_id_rejection("a;b")
        assert ";" in reason

    def test_length_reason_is_specific(self) -> None:
        reason = describe_model_id_rejection("a" * 121)
        assert "120" in reason

    def test_empty_reason_is_specific(self) -> None:
        assert "empty" in describe_model_id_rejection("")

    def test_reasons_for_distinct_causes_are_distinct_strings(self) -> None:
        reasons = {
            describe_model_id_rejection("-x"),
            describe_model_id_rejection(":free"),
            describe_model_id_rejection("a::b"),
            describe_model_id_rejection("a;b"),
            describe_model_id_rejection("a" * 121),
            describe_model_id_rejection(""),
            describe_model_id_rejection("a/../b"),
        }
        assert len(reasons) == 7, "distinct failure causes collapsed to the same message"


class TestPydanticValidatorUsesReason:

    def test_valid_variant_id_accepted(self) -> None:
        req = CreateSessionRequest(model="vendor/model:free")
        assert req.model == "vendor/model:free"

    def test_none_model_accepted(self) -> None:
        req = CreateSessionRequest(model=None)
        assert req.model is None

    def test_invalid_model_raises_with_specific_reason(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateSessionRequest(model="-x")
        assert "flag" in str(exc_info.value)

    def test_invalid_colon_placement_raises_with_specific_reason(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            CreateSessionRequest(model=":free")
        assert "start or end with ':'" in str(exc_info.value)


class TestProviderModelsRouteRejectsWithReason:

    def test_add_provider_model_request_accepts_variant_id(self) -> None:
        body = AddProviderModelRequest(model="vendor/model:free")
        assert body.model == "vendor/model:free"

    @pytest.mark.asyncio
    async def test_invalid_id_raises_400_with_specific_detail(self) -> None:
        from fastapi import HTTPException
        from src.api.provider_models_routes import add_provider_model

        body = AddProviderModelRequest(model=":free")
        with pytest.raises(HTTPException) as exc_info:
            await add_provider_model(body)
        assert exc_info.value.status_code == 400
        assert "start or end with ':'" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_leading_hyphen_id_raises_400_naming_the_flag_risk(self) -> None:
        from fastapi import HTTPException
        from src.api.provider_models_routes import add_provider_model

        body = AddProviderModelRequest(model="--dangerously-skip-permissions")
        with pytest.raises(HTTPException) as exc_info:
            await add_provider_model(body)
        assert exc_info.value.status_code == 400
        assert "flag" in exc_info.value.detail


class TestShlexQuoteDefenseInDepth:

    def test_source_quotes_every_positional_in_agent_wrappers(self) -> None:
        src = Path("src/core/agent_wrappers.py").read_text(encoding="utf-8")
        assert "positional = [model] if model else []" in src, (
            "the model is no longer the head of the positional list"
        )
        assert "shlex.quote(a) for a in positional" in src, (
            "positionals are no longer quoted element by element"
        )

    def test_render_wrapper_invocation_quotes_colon_model_safely(self) -> None:
        from src.core.agent_wrappers import AgentWrapper, render_wrapper_invocation

        wrapper = AgentWrapper(
            id="test-wrapper",
            label="Test Wrapper",
            script="echo hello",
            entry="",
        )
        model_id = "vendor/model:free"
        scripts_dir = Path("/tmp/cc-model-colon-test-scripts")
        outer = render_wrapper_invocation(wrapper, scripts_dir, model=model_id)

        tokens = shlex.split(outer)
        assert tokens[-1] == model_id

    def test_render_wrapper_invocation_rejects_no_quoting_regression(self) -> None:
        from src.core.agent_wrappers import AgentWrapper, render_wrapper_invocation

        wrapper = AgentWrapper(
            id="test-wrapper-2",
            label="Test Wrapper 2",
            script="echo hello",
            entry="",
        )
        model_id = "vendor/model:free"
        scripts_dir = Path("/tmp/cc-model-colon-test-scripts")
        outer = render_wrapper_invocation(wrapper, scripts_dir, model=model_id)
        assert f"{shlex.quote(model_id)}" in outer
