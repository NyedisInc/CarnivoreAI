
import re


MODEL_ID_PATTERN = (
    r"^(?!-)(?!.*\.\.)(?=.{1,120}$)"
    r"[A-Za-z0-9._~/-]+(?::[A-Za-z0-9._~/-]+)?$"
)
_MODEL_ID_RE = re.compile(MODEL_ID_PATTERN)

_ALLOWED_CHAR_RE = re.compile(r"[A-Za-z0-9._~/:-]")


def is_valid_model_id(v: str) -> bool:
    return bool(_MODEL_ID_RE.fullmatch(v))


def describe_model_id_rejection(v: str) -> str:
    if not v:
        return "model id must not be empty"
    if v.startswith("-"):
        return "model id must not start with '-' (would be parsed as a shell flag)"
    if v.startswith(":") or v.endswith(":"):
        return "model id must not start or end with ':'"
    if v.count(":") > 1:
        return "model id must contain at most one ':' variant separator"
    if ".." in v:
        return "model id must not contain '..'"
    bad_chars = sorted(set(ch for ch in v if not _ALLOWED_CHAR_RE.match(ch)))
    if bad_chars:
        return f"model id contains disallowed character(s): {''.join(bad_chars)!r}"
    if len(v) > 120:
        return "model id exceeds the 120 character limit"
    return f"model id does not match required format {MODEL_ID_PATTERN}"
