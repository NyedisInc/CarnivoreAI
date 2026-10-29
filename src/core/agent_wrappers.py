
from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from src.core.agent_families import (
    AGENT_FAMILY_NAMES,
    DEFAULT_FAMILY,
    is_valid_family,
)
from src.core.agent_last_resort import example_wrapper
from src.core.safe_file_write import write_private_file
from src.core.shell_init import rc_prefixed

WRAPPER_SCRIPT_MODE = 0o600

WRAPPER_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
_WRAPPER_ID_RE = re.compile(WRAPPER_ID_PATTERN)

ICON_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
_ICON_ID_RE = re.compile(ICON_ID_PATTERN)


def is_valid_wrapper_id(v: str) -> bool:
    return bool(_WRAPPER_ID_RE.fullmatch(v))


MODEL_CAPABLE_TEXT_RE = re.compile(r"openrouter|\bmodel\b", re.IGNORECASE)


def derive_accepts_model(wrapper: dict) -> bool:
    haystack = " ".join(
        str(wrapper.get(key) or "")
        for key in ("label", "description", "script", "entry")
    )
    return bool(MODEL_CAPABLE_TEXT_RE.search(haystack))


class AgentWrapper(BaseModel):
    """One user-defined launch wrapper for the "claude" agent family.

    - ``id``: stable identifier. Doubles as the ``agent_type`` value a
      caller passes to launch through this specific wrapper (see
      ``Settings.get_agent_command``) and as the on-disk script filename.
      NEVER rename one: ``Session.agent_type`` stores it, so a rename
      orphans every running and historical session launched through it.
    - ``family``: which command family this wrapper wraps - one of
      ``src/core/agent_families.AGENT_FAMILY_NAMES`` (claude, codex,
      hermes, openclaw, shell). Defaults to ``"claude"`` because every
      wrapper that existed before this field was, by construction, a
      claude wrapper; the v2->v3 migration writes that value explicitly.
      A family always has at least one wrapper: its standard one is
      seeded when it has none (``src/core/launch_wrappers``).
    - ``label``: human-readable name shown in the UI.
    - ``script``: the full shell source - a plain command, or a complete
      function definition. Never validated for shell syntax (arbitrary
      user shell, same trust level as the pre-existing ``claude_command``
      field); written verbatim to disk, never interpolated into a quoted
      string.
    - ``entry``: function name to invoke after sourcing ``script``. Unset
      (None/empty) means ``script`` is directly runnable on its own - the
      common case for a migrated single command or a thin
      ``cld "$@"``-style forwarder to a function the user's own
      ``~/.zshrc`` defines. Set it when ``script`` is a function
      definition that needs an explicit call, e.g. ``entry="cld"`` for a
      pasted ``cld() ( ... )`` body.
    - ``description``: optional free-text note shown in the editor.
    - ``default``: at most one wrapper should carry this; the resolver
      falls back to the first wrapper in list order if none (or more than
      one, from a hand-edited config.json) is marked default.
    - ``accepts_model``: whether this wrapper consumes an OpenRouter model
      id as its first argument (the ``cldor`` shape). Model choice and
      wrapper choice are two INDEPENDENT axes; collapsing them into one
      flat picker list is what caused the regression this field fixes -
      a model chosen next to a wrapper that ignores models got forwarded
      to the DEFAULT wrapper, whose ``"$@"`` passed the model id through
      to ``claude`` as a PROMPT ARGUMENT. Defaults to ``False`` so a
      wrapper that says nothing about models is never offered one and
      behaviour for every existing wrapper is unchanged; the v1->v2
      migration seeds a derived value once (see ``derive_accepts_model``).
      ``Settings.get_agent_command`` drops the model outright when the
      resolved wrapper does not accept one, so the picker's rule is
      enforced server-side too, not just in the UI.
    - ``icon``: an icon id from the shared icon picker (issue #1004,
      ``docs/icon-picker.md``), or None. None means "the family's own
      mark", which is what every surface draws for it. Only its shape is
      checked here; ``PUT /api/v1/wrappers/{id}/icon`` checks the id is
      one the picker offers. No colour: the mark wears its parent's.

    SECURITY: there is deliberately no "secret" field. A wrapper is a
    shell command - secrets must never be pasted into ``script`` or
    ``description``. The correct pattern, which the author's own ``cld``
    demonstrates, is to read from the macOS Keychain at *run time* inside
    the script (``security find-generic-password ...``), so no credential
    ever passes through this app or lands in config.json.
    """

    id: str = Field(..., description="Stable id; also the on-disk script filename and the agent_type value")
    family: str = Field(
        DEFAULT_FAMILY,
        description="Which command family this wrapper wraps (see src/core/agent_families.py)",
    )
    label: str = Field(..., description="Human-readable name shown in the UI")
    script: str = Field(..., description="Full shell source: a command or a function definition")
    entry: Optional[str] = Field(
        None,
        description="Function name to call after sourcing script; unset = script is directly runnable",
    )
    description: Optional[str] = Field(None, description="Optional free-text note")
    default: bool = Field(False, description="Preferred wrapper when none is explicitly selected")
    accepts_model: bool = Field(
        False,
        description="Whether this wrapper consumes an OpenRouter model id as its first argument",
    )
    icon: Optional[str] = Field(
        None,
        description="Icon id from client/js/icons/icon-registry.js; None = the family mark",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, v: str) -> str:
        if not is_valid_wrapper_id(v):
            raise ValueError(f"wrapper id must match {WRAPPER_ID_PATTERN}")
        return v

    @field_validator("family", mode="before")
    @classmethod
    def _validate_family(cls, v: Optional[str]) -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return DEFAULT_FAMILY
        name = str(v).strip().lower()
        if not is_valid_family(name):
            raise ValueError(
                f"unknown agent family '{v}'; expected one of {', '.join(AGENT_FAMILY_NAMES)}"
            )
        return name

    @field_validator("icon", mode="before")
    @classmethod
    def _validate_icon(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        if not isinstance(v, str) or not _ICON_ID_RE.fullmatch(v):
            raise ValueError(f"icon must match {ICON_ID_PATTERN}")
        return v

    @field_validator("script")
    @classmethod
    def _validate_script_nonblank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("wrapper script must not be blank")
        return v


def find_wrapper(wrappers: List[AgentWrapper], wrapper_id: str) -> Optional[AgentWrapper]:
    for w in wrappers:
        if w.id == wrapper_id:
            return w
    return None


def default_wrapper(wrappers: List[AgentWrapper]) -> Optional[AgentWrapper]:
    if not wrappers:
        return None
    for w in wrappers:
        if w.default:
            return w
    return wrappers[0]


def wrapper_scripts_dir(log_directory: str) -> Path:
    return Path(log_directory).expanduser() / "agent_wrapper_scripts"


def _write_script_file(wrapper: AgentWrapper, scripts_dir: Path) -> Path:
    return write_private_file(
        scripts_dir,
        f"{wrapper.id}.zsh",
        wrapper.script.encode("utf-8"),
        WRAPPER_SCRIPT_MODE,
    )


_DISABLE_ALTERNATE_SCREEN = "export CLAUDE_CODE_DISABLE_ALTERNATE_SCREEN=1"


def render_wrapper_invocation(
    wrapper: AgentWrapper,
    scripts_dir: Path,
    model: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    disable_alternate_screen: bool = False,
    source_rc: bool = True,
) -> str:
    path = _write_script_file(wrapper, scripts_dir)
    return render_script_invocation(
        path, wrapper.entry, model=model, extra_args=extra_args,
        disable_alternate_screen=disable_alternate_screen, source_rc=source_rc,
    )


def render_script_invocation(
    script_path: Path,
    entry: Optional[str],
    model: Optional[str] = None,
    extra_args: Optional[List[str]] = None,
    disable_alternate_screen: bool = False,
    source_rc: bool = True,
    preamble: str = "",
) -> str:
    inner = f"source {shlex.quote(str(script_path))} \"$@\""
    if disable_alternate_screen:
        inner = f"{_DISABLE_ALTERNATE_SCREEN}; {inner}"
    if preamble:
        inner = f"{preamble}; {inner}"
    if entry and entry.strip():
        inner += f"; {shlex.quote(entry.strip())} \"$@\""
    outer = rc_prefixed(inner) if source_rc else f"zsh -c {shlex.quote(inner)}"
    positional = [model] if model else []
    positional += [a for a in (extra_args or []) if a]
    if positional:
        outer += " _ " + " ".join(shlex.quote(a) for a in positional)
    return outer



EXAMPLE_WRAPPER_CLD = """cld() (
    local claude_token
    claude_token="$(security find-generic-password -a "$USER" -s "claude-cld-oauth" -w 2>/dev/null)" || {
        echo "Claude OAuth token not found in macOS Keychain."
        echo "Run: claude setup-token"
        return 1
    }
    unset CLAUDE_CONFIG_DIR
    export CLAUDE_CODE_OAUTH_TOKEN="$claude_token"
    unset OPENROUTER_API_KEY
    unset ANTHROPIC_BASE_URL
    unset ANTHROPIC_AUTH_TOKEN
    unset ANTHROPIC_API_KEY
    unset CLAUDE_CODE_USE_BEDROCK
    unset CLAUDE_CODE_USE_VERTEX
    unset CLAUDE_CODE_USE_FOUNDRY
    unset ANTHROPIC_MODEL
    unset ANTHROPIC_DEFAULT_OPUS_MODEL
    unset ANTHROPIC_DEFAULT_SONNET_MODEL
    unset ANTHROPIC_DEFAULT_HAIKU_MODEL
    unset CLAUDE_CODE_SUBAGENT_MODEL
    command claude --dangerously-skip-permissions "$@"
)"""

EXAMPLE_WRAPPER_CLDOR = """cldor() (
  local openrouter_key
  local selected_model=""
  local claude_bin

  openrouter_key="$(
    security find-generic-password \\
      -a "$USER" \\
      -s "claude-cldor-openrouter" \\
      -w 2>/dev/null
  )" || {
    echo "OpenRouter API key not found in macOS Keychain."
    return 1
  }

  # Resolve the real claude binary, stepping past any shell-level alias or
  # function of the same name. A bare `command -v claude` reports the ALIAS
  # DEFINITION TEXT when an alias exists, which is not a path and is not
  # executable. The unalias/unset run inside this command substitution's own
  # subshell, so the caller's alias and function survive untouched.
  claude_bin="$(unalias claude 2>/dev/null; unset -f claude 2>/dev/null; command -v claude)"
  if [[ ! -x "$claude_bin" ]]; then
    echo "claude not found on PATH."
    return 1
  fi

  # Treat the first non-option argument as the model name
  if [[ $# -gt 0 && "$1" != -* ]]; then
    selected_model="$1"
    shift
  fi

  # Separate OpenRouter settings, sessions, plugins and history
  export CLAUDE_CONFIG_DIR="$HOME/.claude-cldor"

  # Prevent normal Claude subscription authentication from leaking in
  unset CLAUDE_CODE_OAUTH_TOKEN

  # Prevent cloud-provider routing
  unset CLAUDE_CODE_USE_BEDROCK
  unset CLAUDE_CODE_USE_VERTEX
  unset CLAUDE_CODE_USE_FOUNDRY

  # OpenRouter connection
  export OPENROUTER_API_KEY="$openrouter_key"
  export ANTHROPIC_BASE_URL="https://openrouter.ai/api"
  export ANTHROPIC_AUTH_TOKEN="$openrouter_key"

  # OpenRouter requires this to be explicitly blank
  export ANTHROPIC_API_KEY=""

  if [[ -n "$selected_model" ]]; then
    # Use the command-line model for all Claude Code model roles
    export ANTHROPIC_DEFAULT_OPUS_MODEL="$selected_model"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="$selected_model"
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="$selected_model"
    export CLAUDE_CODE_SUBAGENT_MODEL="$selected_model"

    echo "OpenRouter model: $selected_model"

    "$claude_bin" \\
      --dangerously-skip-permissions \\
      --model "$selected_model" \\
      "$@"
  else
    # Defaults when no model is supplied
    export ANTHROPIC_DEFAULT_OPUS_MODEL="~anthropic/claude-opus-latest"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="~anthropic/claude-sonnet-latest"
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="~anthropic/claude-haiku-latest"
    export CLAUDE_CODE_SUBAGENT_MODEL="~anthropic/claude-opus-latest"

    "$claude_bin" \\
      --dangerously-skip-permissions \\
      "$@"
  fi
)"""

EXAMPLE_WRAPPERS: List[dict] = [
    {
        "id": "cld",
        "family": "claude",
        "label": "cld (subscription, keychain-backed)",
        "script": EXAMPLE_WRAPPER_CLD,
        "entry": "cld",
        "description": (
            "example - reads a Claude subscription OAuth token from the "
            "macOS Keychain at run time (entry 'claude setup-token' first) "
            "and clears every OpenRouter/Bedrock/Vertex env var so it can't "
            "accidentally inherit routing from a prior shell."
        ),
        "default": False,
        "accepts_model": False,
    },
    {
        "id": "cldor",
        "family": "claude",
        "label": "cldor (openrouter, keychain-backed)",
        "script": EXAMPLE_WRAPPER_CLDOR,
        "entry": "cldor",
        "description": (
            "example - takes a model id as its first argument, reads an "
            "OpenRouter API key from the macOS Keychain, and runs Claude "
            "Code isolated in its own CLAUDE_CONFIG_DIR so it never shares "
            "session/auth state with a subscription-mode launch."
        ),
        "default": False,
        "accepts_model": True,
    },
    example_wrapper("codex", "codex", "codex", "codex (guarded)"),
    example_wrapper("hermes", "hermes", "hermes", "hermes (guarded)"),
    example_wrapper("openclaw", "openclaw", "openclaw tui", "openclaw (guarded)"),
    {
        "id": "cldl",
        "family": "local",
        "label": "cldl (lm studio)",
        "script": (
            'cldl() (\n'
            '    local host="${CLDL_HOST:?no LM Studio address: set '
            'providers.local_host in config.json}"\n'
            '    local model="${1:?cldl needs a model id as its first argument}"\n'
            '    export ANTHROPIC_BASE_URL="http://${host}"\n'
            '    export ANTHROPIC_API_KEY="lm-studio"\n'
            '    command claude --dangerously-skip-permissions '
            '--model "$model" "${@:2}"\n'
            ')'
        ),
        "entry": "cldl",
        "description": (
            "example - runs Claude Code against a local LM Studio server "
            "instead of the hosted API. Takes a model id as its first "
            "argument and reads the server address from CLDL_HOST, which "
            "the app sets from providers.local_host; it refuses to launch "
            "rather than guess either one."
        ),
        "default": False,
        "accepts_model": True,
    },
]
