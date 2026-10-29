
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
    """Explain WHY a model id failed ``is_valid_model_id``, distinguishably.

    Description: a rejected model id must say why it was rejected rather
      than reporting one collapsed "invalid" message for every cause - a
      leading hyphen (shell-flag injection), a stray shell metacharacter,
      and a malformed colon-variant suffix are different failure classes
      with different fixes for the caller, and collapsing them into a
      single "model must match {pattern}" makes every 400 equally
      uninformative. Checks run in a fixed priority order (empty, leading
      hyphen, colon placement, ``..``, other disallowed characters, length)
      so a string that trips more than one rule still gets one clear
      answer rather than a random one. Only called on a value that has
      already failed ``is_valid_model_id`` - it does not re-derive
      validity, it explains an already-established rejection.
    Inputs: v (str) - the rejected candidate model id.
    Output: str - a human-readable reason, safe to put in an HTTP 400
      ``detail`` (never echoes back more than the offending characters).
    Example: describe_model_id_rejection("-x") ->
      "model id must not start with '-' (would be parsed as a shell flag)"
    """
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
