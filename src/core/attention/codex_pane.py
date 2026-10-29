
from __future__ import annotations

from src.core.attention.codex_reader import CodexPaneFacts

RESTING_CORE: str = "Ask Codex to do anything"

_BRAILLE_LO = 0x2800
_BRAILLE_HI = 0x28FF

_SPINNER_GLYPHS = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")

_WORKING_MARKERS = ("esc to interrupt",)

_APPROVAL_MARKERS = (
    "would you like to run the following",
    "would you like to grant these permissions",
    "would you like to make the following edits",
    "yes, just this once",
    "no, and tell codex what to do differently",
    "press enter to confirm or esc to cancel",
    "enter to submit answer",
)

_ACTION_REQUIRED = "Action Required"

_TRUST_MARKER = "Do you trust the contents of this directory?"


def _strip_braille(line: str) -> str:
    return "".join(
        ch for ch in line if not (_BRAILLE_LO <= ord(ch) <= _BRAILLE_HI)
    )


def _has_elapsed_timer(text: str) -> bool:
    i = text.find("(")
    while i != -1:
        j = i + 1
        while j < len(text) and text[j].isdigit():
            j += 1
        if j > i + 1 and j < len(text) and text[j] == "s":
            return True
        i = text.find("(", i + 1)
    return False


def classify_codex_pane(text: str, pane_title: str = "") -> CodexPaneFacts:
    """Classify one Codex pane capture into the reader's tri-state facts.

    Description: PURE. A blank capture (no non-space text and no title) is a
      FAILED READ and answers all-None, never "the screen is clear", for the
      same reason claude's classifier does: capture-pane on a full-screen TUI
      can return only trailing blanks. Text we actually read answers True or
      False per marker family, and ``resting_prompt`` is True only when the
      dust-free core is present AND no working or dialog marker is.
    Inputs:
      text (str) - the captured pane body.
      pane_title (str) - the tmux ``#{pane_title}``, which carries the
        spinner and the Action Required marker.
    Output: CodexPaneFacts.
    Example: classify_codex_pane("› Ask Codex to do anything").resting_prompt
      -> True
    """
    body = text or ""
    title = pane_title or ""
    if not body.strip() and not title.strip():
        return CodexPaneFacts(detail="codex pane capture was blank")

    working = (
        any(g in title for g in _SPINNER_GLYPHS)
        or any(m in body for m in _WORKING_MARKERS)
        or _has_elapsed_timer(body)
    )

    trust = _TRUST_MARKER in body

    approval = (
        any(m in " ".join(body.lower().split()) for m in _APPROVAL_MARKERS)
        or _ACTION_REQUIRED in title
    )

    core_present = any(
        RESTING_CORE in _strip_braille(line) for line in body.splitlines()
    )
    resting = core_present and not working and not approval and not trust

    return CodexPaneFacts(
        approval_dialog=approval,
        trust_dialog=trust,
        resting_prompt=resting,
        working_marker=working,
        detail="codex pane read: %s"
        % (
            "approval dialog"
            if approval
            else "trust dialog"
            if trust
            else "working"
            if working
            else "resting prompt"
            if resting
            else "no marker"
        ),
    )
