
from __future__ import annotations

import re
from typing import Any, Dict, Mapping, Optional, Tuple

DECISION_ALWAYS = "always"
DECISION_NEVER = "never"
DECISION_ONCE = "once"
"""Spelled here so the refusal below can name it, NOT because it is
storable. A ``once`` is runtime state in one browser tab."""

PERSISTABLE_DECISIONS = (DECISION_ALWAYS, DECISION_NEVER)

SOURCE_BUILTIN = "builtin"
SOURCE_USER = "user"

RUN = "run"
"""The only outcome that executes anything."""

SKIP_NO_SCRIPT = "skip_no_script"
SKIP_DENIED = "skip_denied"
SKIP_UNVERIFIABLE = "skip_unverifiable"
PROMPT = "prompt"
PROMPT_CHANGED = "prompt_changed"

RUNNING_OUTCOMES = frozenset({RUN})
"""One entry, on purpose. A caller asks this set whether to execute
rather than comparing against a list of refusals that a new rung could be
added to without anyone noticing."""

RUNG_NO_SCRIPT = "no_script"
RUNG_DENIED = "denied"
RUNG_RECORD_UNREADABLE = "record_unreadable"
RUNG_BUILTIN = "builtin"
RUNG_FIRST_PARTY = "first_party"
SCRIPT_TRUST_FIRST_PARTY = "first_party"
RUNG_DIGEST_UNAVAILABLE = "digest_unavailable"
RUNG_DIGEST_MISMATCH = "digest_mismatch"
RUNG_GRANTED = "granted"
RUNG_NO_RECORD = "no_record"

DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

MAX_THEME_ID_LENGTH = 128
"""Comfortably inside the 255-byte limit every filesystem this runs on
imposes on a single name, and bounded so the shared preference block
cannot be grown by a theme with a pathological folder name."""

THEME_ID_RE = re.compile(
    r"^[A-Za-z0-9_](?:[A-Za-z0-9._ -]{0,%d}[A-Za-z0-9._-])?\Z"
    % (MAX_THEME_ID_LENGTH - 2)
)
"""What a theme id may be, for EVERY consumer of one.

A theme id is the theme's DIRECTORY NAME - ``_load_manifest`` refuses a
manifest whose ``id`` disagrees with the folder it was read from - and it
then has to survive four more places: a path segment, a URL path segment,
a JSON object key in the shared ``theme_script_consent`` map, and the
``theme`` preference naming which theme is selected. A folder name this
pattern refuses is a folder whose "never" cannot be recorded, which is why
widening it was a correctness fix and not a convenience.

WHAT IS ALLOWED, AND WHY IT IS SAFE IN ALL FIVE PLACES. Letters, digits,
``.``, ``_``, ``-`` and THE SPACE. A space is an ordinary character in a
folder name (``Neon Rain`` is not exotic), it is a legal JSON key, and
``effectsUrlFor`` in ``client/js/themes/registry.js`` already passes the id
through ``encodeURIComponent``, so it never reaches a URL unencoded. A
leading underscore is allowed because nothing anywhere treats one
specially.

WHAT IS REFUSED, EACH FOR A NAMED REASON, because a charset widened
without this list is how the next hole gets in.

- A LEADING ``.``: a dotted directory is hidden, and ``_scan_themes_root``
  already skips one, so accepting it here would record consent for a theme
  the scanner will never offer. It also makes ``.`` and ``..`` refuse
  themselves, which is the traversal case.
- A LEADING ``-``: never argv today, and one flag-shaped id away from
  being argv tomorrow.
- A LEADING OR TRAILING SPACE: invisible on screen, trimmed by some
  transports and not others, so two ids that look identical stop comparing
  equal and a refusal recorded under one is looked up under the other.
- ``/``, ``\\``, NUL AND EVERY CONTROL CHARACTER: path and URL separators,
  and a control character in a config-file key makes the audit record for a
  code-execution grant unreadable.
- ANYTHING NON-ASCII: deliberate, and the only refusal here that costs a
  real user something. The consent map in ``config.json`` IS the audit
  record of what the user let execute, and a key carrying a bidi override,
  a zero-width joiner or a homograph is one an operator cannot read back
  and check. Supporting it properly needs a normalisation and confusables
  policy, which is a bigger change than this and a worse one to make
  hastily on a consent surface. The gap is named rather than hidden: a
  theme whose folder name is non-ASCII still renders, still prompts, and
  still fails CLOSED - what it cannot do is REMEMBER the answer, and
  ``gateEffects`` now tells the user that instead of pretending it saved.

``\\Z`` RATHER THAN ``$``, WHICH IS NOT COSMETIC. Python's ``$`` also
matches immediately before a trailing newline, so the pattern this
replaced accepted ``"matrix\\n"`` - a legal POSIX filename, and a second
spelling of one theme."""


def is_keyable_theme_id(theme_id: Any) -> bool:
    return isinstance(theme_id, str) and bool(THEME_ID_RE.match(theme_id))

MAX_CONSENT_ENTRIES = 256
"""A record per theme the user has ever answered for. Bounded so the
preference block cannot be grown without limit by a client looping over
invented theme ids."""


class ConsentDecision:

    __slots__ = ("outcome", "rung", "digest")

    def __init__(self, outcome: str, rung: str, digest: Optional[str] = None) -> None:
        self.outcome = outcome
        self.rung = rung
        self.digest = digest

    @property
    def may_run(self) -> bool:
        return self.outcome in RUNNING_OUTCOMES

    def as_payload(self) -> Dict[str, Any]:
        return {"outcome": self.outcome, "rung": self.rung, "digest": self.digest}

    def __repr__(self) -> str:
        return f"<ConsentDecision {self.outcome} via {self.rung}>"


def decide(
    *,
    declares_script: bool,
    source: str,
    served_digest: Optional[str],
    record: Optional[Mapping[str, Any]],
    record_readable: bool = True,
    script_trust: Optional[str] = None,
) -> ConsentDecision:
    if not declares_script:
        return ConsentDecision(SKIP_NO_SCRIPT, RUNG_NO_SCRIPT, None)

    entry = record if isinstance(record, Mapping) else None
    decision = entry.get("decision") if entry else None

    if decision == DECISION_NEVER:
        return ConsentDecision(SKIP_DENIED, RUNG_DENIED, served_digest)

    if not record_readable:
        return ConsentDecision(SKIP_UNVERIFIABLE, RUNG_RECORD_UNREADABLE, served_digest)

    if source == SOURCE_BUILTIN:
        return ConsentDecision(RUN, RUNG_BUILTIN, served_digest)

    if source == SOURCE_USER and script_trust == SCRIPT_TRUST_FIRST_PARTY:
        return ConsentDecision(RUN, RUNG_FIRST_PARTY, served_digest)

    if not served_digest or not DIGEST_RE.match(served_digest):
        return ConsentDecision(SKIP_UNVERIFIABLE, RUNG_DIGEST_UNAVAILABLE, None)

    if decision == DECISION_ALWAYS:
        granted_digest = entry.get("digest") if entry else None
        if isinstance(granted_digest, str) and granted_digest == served_digest:
            return ConsentDecision(RUN, RUNG_GRANTED, served_digest)
        return ConsentDecision(PROMPT_CHANGED, RUNG_DIGEST_MISMATCH, served_digest)

    return ConsentDecision(PROMPT, RUNG_NO_RECORD, served_digest)


def record_for(decision: str, digest: Optional[str]) -> Optional[Dict[str, Any]]:
    if decision == DECISION_NEVER:
        return {"decision": DECISION_NEVER}
    if decision == DECISION_ALWAYS:
        if isinstance(digest, str) and DIGEST_RE.match(digest):
            return {"decision": DECISION_ALWAYS, "digest": digest}
        return None
    return None


def validate_consent_map(value: Any) -> Dict[str, Dict[str, Any]]:
    if not isinstance(value, dict):
        raise ValueError("theme script consent must be an object of theme ids")
    if len(value) > MAX_CONSENT_ENTRIES:
        raise ValueError(
            f"at most {MAX_CONSENT_ENTRIES} theme script consent entries"
        )

    out: Dict[str, Dict[str, Any]] = {}
    for theme_id, entry in value.items():
        if not is_keyable_theme_id(theme_id):
            raise ValueError("a theme script consent key must be a theme id")
        if not isinstance(entry, dict):
            raise ValueError("each theme script consent entry must be an object")

        decision = entry.get("decision")
        if decision == DECISION_ONCE:
            raise ValueError(
                "'allow once' is a temporary choice and is never stored"
            )
        if decision not in PERSISTABLE_DECISIONS:
            raise ValueError(
                f"a theme script consent decision must be one of "
                f"{list(PERSISTABLE_DECISIONS)}"
            )

        digest = entry.get("digest")
        if decision == DECISION_ALWAYS:
            if not isinstance(digest, str) or not DIGEST_RE.match(digest):
                raise ValueError(
                    "allowing a theme script requires the digest of the script "
                    "that was approved"
                )
            out[theme_id] = {"decision": DECISION_ALWAYS, "digest": digest}
        else:
            out[theme_id] = {"decision": DECISION_NEVER}

    return out


def revocations_between(
    before: Optional[Mapping[str, Any]], after: Optional[Mapping[str, Any]]
) -> Tuple[str, ...]:
    prior = before if isinstance(before, Mapping) else {}
    current = after if isinstance(after, Mapping) else {}
    moved = []
    for theme_id, entry in current.items():
        if not isinstance(entry, Mapping) or entry.get("decision") != DECISION_NEVER:
            continue
        was = prior.get(theme_id)
        if isinstance(was, Mapping) and was.get("decision") == DECISION_NEVER:
            continue
        moved.append(theme_id)
    return tuple(sorted(moved))
