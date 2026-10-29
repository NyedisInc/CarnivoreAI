
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Match, Optional, Pattern, Tuple

from src.core.message_model_secret_guards import (  # noqa: F401
    MAX_REPEATED_RUN,
    PLACEHOLDER_MARKERS,
    REFERENCE_PREFIXES,
    has_mixed_alphabet,
    is_placeholder,
    is_placeholder_jwt,
    shannon_entropy,
)
from src.core.secret_scanning import aws_name as _aws
from src.core import message_model_secret_redaction as _redact
from src.core.secret_scanning.accepted_matches import accepted_matches
from src.core.secret_scanning.claimed_spans import ClaimedSpans
from src.core.secret_scanning.deadline import Deadline

DETECTOR_OP_SERVICE_ACCOUNT: str = "op_service_account_token"

DETECTOR_HIGH_ENTROPY_ASSIGNMENT: str = "high_entropy_assignment"

DETECTOR_GITHUB_TOKEN: str = "github_token"
DETECTOR_AWS_ACCESS_KEY_ID: str = "aws_access_key_id"
DETECTOR_AWS_SECRET_ACCESS_KEY: str = "aws_secret_access_key"
DETECTOR_GOOGLE_API_KEY: str = "google_api_key"
DETECTOR_SLACK_TOKEN: str = "slack_token"
DETECTOR_PEM_PRIVATE_KEY: str = "pem_private_key"
DETECTOR_CLOUDFLARE_API_TOKEN: str = "cloudflare_api_token"
DETECTOR_MINISIGN_SECRET_KEY: str = "minisign_secret_key"
DETECTOR_ANTHROPIC_API_KEY: str = "anthropic_api_key"
DETECTOR_OPENAI_API_KEY: str = "openai_api_key"
DETECTOR_CARNIVORE_API_KEY: str = "carnivore_api_key"
DETECTOR_BEARER_TOKEN: str = "bearer_token"
DETECTOR_JWT: str = "jwt"
DETECTOR_STRIPE_KEY: str = "stripe_key"
DETECTOR_HUGGINGFACE_TOKEN: str = "huggingface_token"
DETECTOR_NPM_TOKEN: str = "npm_token"
DETECTOR_GITLAB_TOKEN: str = "gitlab_token"
DETECTOR_SENDGRID_KEY: str = "sendgrid_key"
DETECTOR_SLACK_APP_TOKEN: str = "slack_app_token"
DETECTOR_CATALOG_BOT_TOKEN: str = "catalog_bot_token"

VENDOR_DETECTORS: Tuple[str, ...] = (
    DETECTOR_OP_SERVICE_ACCOUNT,
    DETECTOR_GITHUB_TOKEN,
    DETECTOR_AWS_ACCESS_KEY_ID,
    DETECTOR_AWS_SECRET_ACCESS_KEY,
    DETECTOR_GOOGLE_API_KEY,
    DETECTOR_SLACK_TOKEN,
    DETECTOR_PEM_PRIVATE_KEY,
    DETECTOR_CLOUDFLARE_API_TOKEN,
    DETECTOR_MINISIGN_SECRET_KEY,
    DETECTOR_ANTHROPIC_API_KEY,
    DETECTOR_OPENAI_API_KEY,
    DETECTOR_CARNIVORE_API_KEY,
)

EXTRA_VENDOR_DETECTORS: Tuple[str, ...] = (
    DETECTOR_STRIPE_KEY,
    DETECTOR_HUGGINGFACE_TOKEN,
    DETECTOR_NPM_TOKEN,
    DETECTOR_GITLAB_TOKEN,
    DETECTOR_SENDGRID_KEY,
    DETECTOR_SLACK_APP_TOKEN,
    DETECTOR_CATALOG_BOT_TOKEN,
)

ALL_DETECTORS: Tuple[str, ...] = VENDOR_DETECTORS + EXTRA_VENDOR_DETECTORS + (
    DETECTOR_HIGH_ENTROPY_ASSIGNMENT,
    DETECTOR_BEARER_TOKEN,
    DETECTOR_JWT,
)

MIN_VENDOR_ENTROPY_BITS_PER_CHAR: float = 3.0

_ESCAPE_BEFORE = r"(?<=\\[bfnrt])"

_WORD_START = r"(?:(?<!\w)|" + _ESCAPE_BEFORE + r")"

_OP_TOKEN_RE = re.compile(
    r"(?:(?<![A-Za-z0-9])|" + _ESCAPE_BEFORE + r")ops_[A-Za-z0-9+/=_-]{40,}"
)

_ASSIGNMENT_RE = re.compile(
    r"""(?ix)
    (?:token|secret|key|password|passwd|api_key|apikey)
    [\"']?
    \s*[:=]\s*
    [\"']?
    (?P<value>[A-Za-z0-9+/=_\-.]{20,})
    """
)

MIN_ENTROPY_BITS_PER_CHAR: float = 3.5


@dataclass(frozen=True)
class _VendorPattern:

    detector: str
    regex: Pattern[str]
    redact_regex: Pattern[str]
    check_payload: bool = True
    require_mixed_alphabet: bool = False
    placeholder_check: Callable[[str], bool] = is_placeholder
    accept: Optional[Callable[[Match[str]], bool]] = None
    redact_accept: Optional[Callable[[Match[str]], bool]] = None


_GITHUB_RE = re.compile(
    _WORD_START + r"(?:github_pat_\w{82}|gh[pousr]_[A-Za-z0-9]{36,255})\b"
)

_AWS_KEY_ID_RE = re.compile(
    _WORD_START
    + r"(?:AKIA|ASIA|ABIA|ACCA|AGPA|AIDA|AIPA|ANPA|ANVA|AROA)[A-Z0-9]{16}\b"
)

_AWS_SECRET_RE = re.compile(
    r"""(?x)
    (?<![A-Za-z0-9_.\-])
    (?P<name>[A-Za-z0-9_.\-]+)
    [\"']? \s* [:=] \s* [\"']?
    (?P<value>[A-Za-z0-9/+=]{40})
    (?![A-Za-z0-9/+=])
    """
)

_GOOGLE_API_KEY_RE = re.compile(_WORD_START + r"AIza[0-9A-Za-z_\-]{35}\b")

_SLACK_RE = re.compile(_WORD_START + r"xox[abprs]-[A-Za-z0-9\-]{10,}\b")

_STRIPE_RE = re.compile(_WORD_START + r"[rs]k_(?:live|test)_[A-Za-z0-9]{24,99}(?![A-Za-z0-9])")
_HUGGINGFACE_RE = re.compile(_WORD_START + r"hf_[A-Za-z0-9]{30,40}(?![A-Za-z0-9])")
_NPM_RE = re.compile(_WORD_START + r"npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])")
_GITLAB_RE = re.compile(_WORD_START + r"glpat-[A-Za-z0-9_\-]{20,50}(?![A-Za-z0-9_\-])")
_SENDGRID_RE = re.compile(_WORD_START + r"SG\.[A-Za-z0-9_\-]{22}\.[A-Za-z0-9_\-]{43}(?![A-Za-z0-9_\-])")
_CATALOG_BOT_TOKEN_RE = re.compile(_WORD_START + r"cbt_[A-Za-z0-9_\-]{43}(?![A-Za-z0-9_\-])")
_SLACK_APP_RE = re.compile(_WORD_START + r"xapp-[A-Za-z0-9\-]{10,}\b")
_CARNIVORE_API_KEY_RE = re.compile(_WORD_START + r"cak_[A-Za-z0-9_\-]{43}(?![A-Za-z0-9_\-])")

_PEM_RE = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"
    r"(?=[\r\n\s]+[A-Za-z0-9+/=]{20,})"
)

_CLOUDFLARE_RE = re.compile(
    r"""(?ix)
    (?: cloudflare | (?:(?<!\w)|(?<=\\[bfnrt])) cf ) [A-Za-z0-9_.\-]{0,64}
    (?: token | key | secret )
    [\"']? \s* [:=] \s* [\"']?
    (?P<value>[A-Za-z0-9_\-]{37,40})
    (?![A-Za-z0-9_\-])
    """
)

_MINISIGN_SECRET_RE = re.compile(
    r"untrusted comment: *minisign encrypted secret key"
    r"(?=[\r\n\s]+[A-Za-z0-9+/=]{20,})"
)

_ANTHROPIC_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_\-])|" + _ESCAPE_BEFORE + r")sk-ant-(?:api|admin|oat|ort)[0-9]{2}-[A-Za-z0-9_\-]{32,255}"
)

_OPENAI_RE = re.compile(
    r"(?:(?<![A-Za-z0-9_\-])|" + _ESCAPE_BEFORE + r")sk-(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,255}"
)

_BEARER_RE = re.compile(
    r"(?i:bearer)[ \t]+(?P<value>[A-Za-z0-9._~+/\-]{20,}=*)"
)

JWT_RE = re.compile(_redact.JWT_SOURCE)

_VENDOR_PATTERNS: Tuple[_VendorPattern, ...] = (
    _VendorPattern(
        DETECTOR_OP_SERVICE_ACCOUNT, _OP_TOKEN_RE, _redact.OP_SERVICE_ACCOUNT,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_GITHUB_TOKEN, _GITHUB_RE, _redact.GITHUB_TOKEN,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_AWS_ACCESS_KEY_ID, _AWS_KEY_ID_RE, _redact.AWS_ACCESS_KEY_ID,
    ),
    _VendorPattern(
        DETECTOR_AWS_SECRET_ACCESS_KEY, _AWS_SECRET_RE,
        _redact.AWS_SECRET_ACCESS_KEY,
        accept=_aws.accept, redact_accept=_aws.redact_accept,
    ),
    _VendorPattern(
        DETECTOR_GOOGLE_API_KEY, _GOOGLE_API_KEY_RE, _redact.GOOGLE_API_KEY,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(DETECTOR_SLACK_TOKEN, _SLACK_RE, _redact.SLACK_TOKEN),
    _VendorPattern(
        DETECTOR_PEM_PRIVATE_KEY, _PEM_RE, _redact.PEM_PRIVATE_KEY,
        check_payload=False,
    ),
    _VendorPattern(
        DETECTOR_CLOUDFLARE_API_TOKEN, _CLOUDFLARE_RE,
        _redact.CLOUDFLARE_API_TOKEN,
    ),
    _VendorPattern(
        DETECTOR_MINISIGN_SECRET_KEY, _MINISIGN_SECRET_RE,
        _redact.MINISIGN_SECRET_KEY, check_payload=False,
    ),
    _VendorPattern(
        DETECTOR_ANTHROPIC_API_KEY, _ANTHROPIC_RE, _redact.ANTHROPIC_API_KEY,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_OPENAI_API_KEY, _OPENAI_RE, _redact.OPENAI_API_KEY,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_CARNIVORE_API_KEY, _CARNIVORE_API_KEY_RE, _redact.CARNIVORE_API_KEY,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_CATALOG_BOT_TOKEN, _CATALOG_BOT_TOKEN_RE, _redact.CATALOG_BOT_TOKEN,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_STRIPE_KEY, _STRIPE_RE, _redact.STRIPE_KEY,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_HUGGINGFACE_TOKEN, _HUGGINGFACE_RE, _redact.HUGGINGFACE_TOKEN,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_NPM_TOKEN, _NPM_RE, _redact.NPM_TOKEN,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_GITLAB_TOKEN, _GITLAB_RE, _redact.GITLAB_TOKEN,
        require_mixed_alphabet=True,
    ),
    _VendorPattern(
        DETECTOR_SENDGRID_KEY, _SENDGRID_RE, _redact.SENDGRID_KEY,
    ),
    _VendorPattern(
        DETECTOR_SLACK_APP_TOKEN, _SLACK_APP_RE, _redact.SLACK_APP_TOKEN,
    ),
    _VendorPattern(DETECTOR_BEARER_TOKEN, _BEARER_RE, _redact.BEARER_TOKEN),
    _VendorPattern(DETECTOR_JWT, JWT_RE, _redact.JWT, placeholder_check=is_placeholder_jwt),
)


@dataclass(frozen=True)
class SecretFinding:

    detector: str
    offset: int
    length: int
    value_sha256: str

    def __post_init__(self) -> None:
        if self.detector not in ALL_DETECTORS:
            raise ValueError(f"unknown detector: {self.detector!r}")
        if self.length <= 0:
            raise ValueError("SecretFinding.length must be positive")


def _finding(detector: str, value: str, offset: int) -> SecretFinding:
    return SecretFinding(
        detector=detector,
        offset=offset,
        length=len(value),
        value_sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(),
    )


def _vendor_guard_drops(pattern: _VendorPattern, value: str) -> bool:
    if pattern.check_payload and (
        pattern.placeholder_check(value)
        or shannon_entropy(value) < MIN_VENDOR_ENTROPY_BITS_PER_CHAR
    ):
        return True
    return pattern.require_mixed_alphabet and not has_mixed_alphabet(value)


def scan_text(
    text: str,
    detectors: Optional[Iterable[str]] = None,
    *,
    trust_vendor_marker: bool = False,
    deadline: Optional[Deadline] = None,
) -> List[SecretFinding]:
    wanted = frozenset(ALL_DETECTORS if detectors is None else detectors)
    unknown = wanted - frozenset(ALL_DETECTORS)
    if unknown:
        raise ValueError(f"unknown detector(s): {sorted(unknown)!r}")

    findings: List[SecretFinding] = []
    claimed = ClaimedSpans()

    for pattern in _VENDOR_PATTERNS:
        if pattern.detector not in wanted:
            continue
        if deadline is not None:
            deadline.check()
        regex = pattern.redact_regex if trust_vendor_marker else pattern.regex
        accept = pattern.redact_accept if trust_vendor_marker else pattern.accept
        claims: List[Tuple[int, int]] = []
        for match in accepted_matches(regex, text, accept):
            if deadline is not None:
                deadline.check()
            has_value = "value" in (match.groupdict() or {})
            group = "value" if has_value else 0
            value = match.group(group)
            if not trust_vendor_marker and _vendor_guard_drops(pattern, value):
                continue
            start, end = match.span(group)
            if claimed.overlaps(start, end):
                continue
            findings.append(_finding(pattern.detector, value, start))
            claims.append((start, end))
        if claims:
            claimed.merge(claims)

    if DETECTOR_HIGH_ENTROPY_ASSIGNMENT in wanted:
        if deadline is not None:
            deadline.check()
        for match in _ASSIGNMENT_RE.finditer(text):
            if deadline is not None:
                deadline.check()
            value = match.group("value")
            start = match.start("value")
            end = match.end("value")
            if claimed.overlaps(start, end):
                continue
            if is_placeholder(value):
                continue
            if shannon_entropy(value) < MIN_ENTROPY_BITS_PER_CHAR:
                continue
            findings.append(
                _finding(DETECTOR_HIGH_ENTROPY_ASSIGNMENT, value, start)
            )

    findings.sort(key=lambda f: f.offset)
    return findings
