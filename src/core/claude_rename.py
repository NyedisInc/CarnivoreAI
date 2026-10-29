"""Push a CloudeCode rename through to Claude Code's own session name.

WHY THIS EXISTS. CloudeCode's rename and Claude Code's rename are two
different names for the same session, and until now only the first one
moved. Claude Code has carried ``/rename <name>`` since v2.1.205 and
``-n/--name`` at launch, and it keeps the result in its own transcript as
a ``custom-title`` row - so the session the user renamed in the browser
went on calling itself something else in the prompt bar, the ``/resume``
picker and the terminal title.

WHAT THIS CANNOT DO, and it shapes everything below: there is no
``SessionRename`` hook event (verified against the shipped 2.1.248 binary:
zero occurrences), and ``/rename`` does NOT fire ``UserPromptSubmit``,
because Claude intercepts slash commands before they become prompts. So
no EVENT can carry the news: CloudeCode can push a name TO Claude, and it
can never be TOLD that a user typed ``/rename`` in the terminal.

  PUSH_SENT       - the conversation is addressable; the child was run.
  PUSH_DEFERRED   - no uuid is bound yet, or its transcript is measurably
                    absent, or the label is one Claude would rewrite.
                    Nothing was sent. This is NOT a failure: the name is
                    already stored on our side, and Claude's copy can be
                    pushed later or set by the user.
  PUSH_UNSUPPORTED- this session is not a Claude session, or the running
                    Claude is older than ``MIN_RENAME_VERSION``.

Never invent a fourth meaning by returning PUSH_SENT for a send whose
effect was not observed. A queued keystroke is not a rename.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)

MIN_RENAME_VERSION: Tuple[int, int, int] = (2, 1, 205)

PUSH_SENT: str = "sent"
PUSH_DEFERRED: str = "deferred"
PUSH_UNSUPPORTED: str = "unsupported"

MAX_NAME_CHARS: int = 200


def parse_claude_version(text: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not text:
        return None
    head = text.strip().split()[0] if text.strip() else ""
    parts = head.split(".")
    if len(parts) < 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def supports_rename(version: Optional[Tuple[int, int, int]]) -> bool:
    if version is None:
        return False
    return version >= MIN_RENAME_VERSION


def name_is_pushable(label: str) -> bool:
    if not label or not label.strip():
        return False
    if len(label) > MAX_NAME_CHARS:
        return False
    return all(ch == " " or ch.isprintable() for ch in label)


# not a guarantee
OOB_TIMEOUT_SECONDS: int = 15


def oob_rename_argv(
    claude_path: str, claude_uuid: str, label: str
) -> List[str]:
    return [
        claude_path,
        "-p",
        "--resume",
        claude_uuid,
        f"/rename {label}",
    ]


def decide_push(
    *,
    label: str,
    claude_uuid: Optional[str],
    claude_version: Optional[Tuple[int, int, int]],
    is_claude_session: bool,
    transcript_presence: Optional[str] = None,
) -> Tuple[str, str]:
    from src.core.session_transcript_presence import CONVERSATION_ABSENT
    if not is_claude_session:
        return (PUSH_UNSUPPORTED, "not a Claude session")
    if not supports_rename(claude_version):
        shown = ".".join(str(p) for p in claude_version) if claude_version else "unknown"
        return (
            PUSH_UNSUPPORTED,
            f"claude {shown} has no /rename (needs "
            f"{'.'.join(str(p) for p in MIN_RENAME_VERSION)}+)",
        )
    if not name_is_pushable(label):
        return (
            PUSH_DEFERRED,
            "claude would rewrite this name, so the two sides would "
            "disagree - not sending",
        )
    if not claude_uuid:
        return (
            PUSH_DEFERRED,
            "no Claude conversation uuid is bound yet, so there is "
            "nothing for --resume to address",
        )
    if transcript_presence == CONVERSATION_ABSENT:
        return (
            PUSH_DEFERRED,
            "a conversation uuid is bound but its transcript is not on "
            "this machine yet, and --resume against a missing transcript "
            "exits without renaming anything",
        )
    return (PUSH_SENT, "out of band via --resume, no pane contact")


def rename_command(label: str) -> str:
    return f"/rename {label}"


RENAME_CAPABLE_FAMILY: str = "claude"


def launch_name_args(
    *,
    label: Optional[str],
    family: Optional[str],
    claude_version: Optional[Tuple[int, int, int]],
) -> list:
    if not label or family != RENAME_CAPABLE_FAMILY:
        return []
    if not supports_rename(claude_version):
        return []
    if not name_is_pushable(label):
        return []
    return ["--name", label]


def detect_claude_version() -> Optional[Tuple[int, int, int]]:
    """
    Description: reuses ``server_status.collect_claude_cli`` rather than
      running its own probe. That module already solves the hard part -
      ``claude`` is not on a non-interactive shell's PATH here, so it
      walks absolute candidates - and a second resolver would be free to
      disagree with the one the status page shows, which is how two
      sources of truth start.

      Returns None on ANY failure, and None means unsupported everywhere
      it is consumed. Import errors and subprocess failures are caught
      together on purpose: from this function's point of view they are
      the same fact, which is "I could not establish a version", and the
      caller must not send a command on the strength of a guess.
    Inputs: none.
    Output: tuple[int, int, int] | None.
    Example: detect_claude_version() -> (2, 1, 248)
    """
    try:
        from src.core.server_status import collect_claude_cli

        info = collect_claude_cli()
    except Exception as exc:  # noqa: BLE001
        logger.debug("claude_version_probe_failed", error=str(exc))
        return None
    if not info or not info.get("available"):
        return None
    return parse_claude_version(info.get("version"))


def launch_name_args_for_agent_type(
    *,
    label: Optional[str],
    agent_type: Optional[str],
    wrappers: Optional[List] = None,
) -> list:
    if not label:
        return []
    try:
        from src.core.agent_families import resolve_agent_type

        resolved, _explicit = resolve_agent_type(agent_type, wrappers or [])
        family = getattr(resolved, "name", None)
        return launch_name_args(
            label=label, family=family, claude_version=detect_claude_version()
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("launch_name_args_failed", error=str(exc))
        return []


def spawn_oob_rename(argv: List[str], *, session_id: str) -> bool:
    import subprocess
    import threading

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        logger.warning(
            "claude_rename_spawn_failed", session_id=session_id, error=str(exc)
        )
        return False

    def _reap() -> None:
        try:
            _out, err = proc.communicate(timeout=OOB_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            logger.warning(
                "claude_rename_push_timed_out",
                session_id=session_id,
                timeout_s=OOB_TIMEOUT_SECONDS,
            )
            return
        except OSError as exc:
            logger.warning(
                "claude_rename_push_unwaitable",
                session_id=session_id,
                error=str(exc),
            )
            return
        if proc.returncode == 0:
            logger.info("claude_rename_push_landed", session_id=session_id)
            return
        logger.warning(
            "claude_rename_push_rejected",
            session_id=session_id,
            exit_code=proc.returncode,
            stderr=(err or b"").decode("utf-8", "replace").strip()[:300],
        )

    threading.Thread(
        target=_reap, name=f"oob-rename-{session_id}", daemon=True
    ).start()
    return True
