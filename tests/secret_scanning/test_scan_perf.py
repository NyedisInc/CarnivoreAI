
from __future__ import annotations

import random
import time
from typing import Callable

import pytest

from src.core.secret_scanning import deadline as scan_deadline
from src.core.secret_scanning.claimed_spans import ClaimedSpans
from src.core.message_model_secrets import DETECTOR_AWS_SECRET_ACCESS_KEY, scan_text
from src.core.secret_scanning.deadline import Deadline, ScanTimeout
from src.core.stream_redactor import redact_whole
from src.cplugs.sdk.file_secrets import credential_counts

_ALNUM = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
_AWS_VALUE = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYzEXAMPLEKE"


def _best_of(fn: Callable[[], object], runs: int = 2) -> float:
    best = float("inf")
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - start)
    return best


def _scan_cost(text: str, detector: str, trust: bool) -> float:
    return _best_of(lambda: scan_text(text, (detector,), trust_vendor_marker=trust))


def _tokens(count: int) -> str:
    rng = random.Random(1)
    return " ".join("ghp_" + "".join(rng.choice(_ALNUM) for _ in range(36)) for _ in range(count))


def test_scan_text_is_not_quadratic_in_findings() -> None:
    small, large = _tokens(3000), _tokens(24000)
    ratio = _scan_cost(large, "github_token", False) / _scan_cost(small, "github_token", False)
    assert ratio < 25


@pytest.mark.parametrize("trust", [False, True])
@pytest.mark.parametrize(
    "unit",
    ["awssecret", "aws" + "secret" * 8 + ": " + "A" * 39 + " ", "aws" + "a" * 60 + "secret" + "b" * 60, ".-:"],
    ids=["flood", "near-miss-values", "long-names", "delimiter-chars"],
)
def test_aws_secret_costs_about_the_same_as_any_other_detector(unit: str, trust: bool) -> None:
    text = (unit * (512 * 1024 // len(unit) + 1))[: 512 * 1024]
    ratio = _scan_cost(text, DETECTOR_AWS_SECRET_ACCESS_KEY, trust) / _scan_cost(text, "github_token", False)
    assert ratio < 15


@pytest.mark.parametrize("before,after,hit", [(64, 64, True), (65, 64, False), (64, 65, False), (0, 0, True)])
def test_aws_secret_name_bounds_are_unchanged(before: int, after: int, hit: bool) -> None:
    name = "aws" + "x" * before + "secret" + "y" * after
    findings = scan_text(f"{name}={_AWS_VALUE}", (DETECTOR_AWS_SECRET_ACCESS_KEY,))
    assert bool(findings) is hit


def test_aws_secret_still_found_in_both_modes() -> None:
    for text in (f"AWS_SECRET_ACCESS_KEY={_AWS_VALUE}", f'"aws_secret": "{_AWS_VALUE}"', f"x.aws-access-key = '{_AWS_VALUE}'"):
        assert [f.length for f in scan_text(text, (DETECTOR_AWS_SECRET_ACCESS_KEY,))] == [40]
        assert _AWS_VALUE not in redact_whole(text)


class _Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_expired_deadline_is_could_not_scan_never_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(scan_deadline, "_now", clock)
    deadline = Deadline(10.0)
    text = f"AWS_SECRET_ACCESS_KEY={_AWS_VALUE}"
    assert len(scan_text(text, deadline=deadline)) == 1
    clock.now += 11.0
    with pytest.raises(ScanTimeout):
        scan_text(text, deadline=deadline)
    with pytest.raises(ScanTimeout):
        credential_counts(text, deadline=deadline)


def test_no_deadline_means_no_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    monkeypatch.setattr(scan_deadline, "_now", clock)
    text = f"AWS_SECRET_ACCESS_KEY={_AWS_VALUE}"
    clock.now += 365 * 24 * 3600.0
    assert len(scan_text(text)) == 1
    assert credential_counts(text) == {DETECTOR_AWS_SECRET_ACCESS_KEY: 1}


@pytest.mark.parametrize("trust", [False, True])
def test_aws_name_rejected_does_not_swallow_a_real_name(trust: bool) -> None:
    glued = f"token={'Q' * 37}aws_secret_access_key={_AWS_VALUE}"
    assert [f.offset for f in scan_text(glued, (DETECTOR_AWS_SECRET_ACCESS_KEY,), trust_vendor_marker=trust)] == [glued.index(_AWS_VALUE)]
    if trust:
        long_name = f"x=AWSsecretAccessKeyForTheProductionBackupAccount:{_AWS_VALUE}"
        assert [f.offset for f in scan_text(long_name, (DETECTOR_AWS_SECRET_ACCESS_KEY,), trust_vendor_marker=True)] == [long_name.index(_AWS_VALUE)]
        assert _AWS_VALUE not in redact_whole(long_name)


def test_aws_name_after_a_rejected_one_with_delimiter_characters_between_is_found() -> None:
    text = f"AWSawsaws'_=-awsAccess={_AWS_VALUE}Access"
    found = scan_text(text, (DETECTOR_AWS_SECRET_ACCESS_KEY,), trust_vendor_marker=True)
    assert found and _AWS_VALUE not in redact_whole(text)


@pytest.mark.parametrize("trust,dots,hit", [(True, 8, True), (True, 9, False), (False, 8, False), (True, 0, True)])
def test_aws_redaction_delimiter_slack_is_exactly_the_dots_and_dashes(trust: bool, dots: int, hit: bool) -> None:
    name = "aws" + "x" * 3 + "secret" + "y" * 64 + "." * dots
    found = scan_text(f"{name}={_AWS_VALUE}", (DETECTOR_AWS_SECRET_ACCESS_KEY,), trust_vendor_marker=trust)
    assert bool(found) is (hit if dots else True)


def test_claimed_spans_reject_empty_spans_and_merge_sorted_batches() -> None:
    claimed = ClaimedSpans()
    with pytest.raises(ValueError):
        claimed.merge([(5, 5)])
    claimed.merge([(10, 20), (30, 40)])
    assert claimed.overlaps(19, 25) and claimed.overlaps(0, 11) and not claimed.overlaps(20, 30)
    claimed.merge([(0, 5), (25, 28)])
    assert claimed.overlaps(26, 27) and not claimed.overlaps(5, 10)


def test_claimed_spans_merge_is_linear_in_the_batch() -> None:
    def run(n: int) -> float:
        def go() -> None:
            claimed = ClaimedSpans()
            for batch in range(21):
                claimed.merge([(i * 22 + batch, i * 22 + batch + 1) for i in range(n)])
        return _best_of(go)
    assert run(40000) / run(10000) < 10
