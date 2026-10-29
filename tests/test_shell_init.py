
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_tests_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_tests_logs_"))
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.shell_init import RC_SOURCE, rc_prefixed
from tests.socket_guard import derive_test_socket




def test_rc_source_closes_stdin():
    assert "</dev/null" in RC_SOURCE


def test_rc_source_still_suppresses_output():
    assert ">/dev/null 2>&1" in RC_SOURCE


def test_rc_source_still_sources_the_users_zshrc():
    assert RC_SOURCE.startswith("source ~/.zshrc")


def test_redirections_are_scoped_to_the_source_builtin():
    built = rc_prefixed("some-agent")
    body = built[len("zsh -c '"):-1]
    before, _, after = body.partition(";")
    assert "</dev/null" in before
    assert ">/dev/null" in before
    assert "/dev/null" not in after
    assert after.strip() == "some-agent"


def test_rc_prefixed_wraps_in_a_single_zsh_c_string():
    assert rc_prefixed("keyc") == (
        "zsh -c 'source ~/.zshrc >/dev/null 2>&1 </dev/null; keyc'"
    )


def test_every_launch_path_uses_the_one_prefix():
    from src.config.agent_command import agent_command
    from src.config.agents import AgentsConfig
    from src.core.agent_families import AGENT_FAMILIES
    from src.core.agent_wrappers import AgentWrapper, render_wrapper_invocation

    scripts = Path(tempfile.mkdtemp(prefix="cc_wrap_"))
    rendered = [
        render_wrapper_invocation(
            AgentWrapper(id="w", label="w", script="keyc() { :; }", entry="keyc"),
            scripts,
        ),
    ]
    for family in AGENT_FAMILIES:
        if not family.sources_zshrc:
            continue
        rendered.append(agent_command(
            family.name,
            agents=AgentsConfig(),
            resolve_state_dir=lambda: str(scripts),
            disable_alternate_screen=lambda: False,
            model="m/one" if family.needs_model else None,
        ))
    for cmd in rendered:
        assert RC_SOURCE in cmd, cmd


def test_a_family_that_does_not_source_rc_is_untouched():
    from src.core.agent_families import get_family
    from src.core.agent_wrappers import AgentWrapper, render_wrapper_invocation

    family = get_family("shell")
    out = render_wrapper_invocation(
        AgentWrapper(id="s", family="shell", label="s", script=family.default_script),
        Path(tempfile.mkdtemp(prefix="cc_wrap_")),
        source_rc=family.sources_zshrc,
    )
    assert RC_SOURCE not in out
    assert out.startswith("zsh -c ")



requires_tmux = pytest.mark.skipif(
    shutil.which("tmux") is None or shutil.which("zsh") is None,
    reason="tmux and zsh required",
)

_RC_FIXTURE = """export FROM_RC=yes
rc_defined_func() { print "rc_defined_func ran"; }
print "BANNER-NOISE"
if [[ -t 0 ]]; then
  printf "Do you want to update the profile? [y/N]: "
  read -r REPLY
  print "PROMPTED"
else
  print "RC-TOOK-NONINTERACTIVE-BRANCH"
fi
"""


def _run_pane(inner: str, socket: str, rc_path: Path) -> str:
    tmux = shutil.which("tmux")
    pane_cmd = f"zsh -f -c {shlex.quote(inner.format(rc=shlex.quote(str(rc_path))))}"
    subprocess.run(
        [tmux, "-L", socket, "new-session", "-d", "-s", "t",
         "-x", "100", "-y", "30", pane_cmd],
        check=True,
    )
    time.sleep(2.0)
    out = subprocess.run(
        [tmux, "-L", socket, "capture-pane", "-p", "-t", "t"],
        capture_output=True, check=True,
    )
    return out.stdout.decode("utf-8", errors="replace")


@pytest.fixture
def tmux_socket():
    name = derive_test_socket("shellinit")
    yield name
    tmux = shutil.which("tmux")
    if tmux:
        subprocess.run([tmux, "-L", name, "kill-server"],
                       capture_output=True, check=False)


@pytest.fixture
def rc_fixture():
    path = Path(tempfile.gettempdir()) / f"cc_rc_{uuid.uuid4().hex[:6]}.zsh"
    path.write_text(_RC_FIXTURE)
    yield path
    path.unlink(missing_ok=True)


@requires_tmux
def test_the_old_prefix_produces_a_completely_blank_pane(tmux_socket, rc_fixture):
    screen = _run_pane(
        "source {rc} >/dev/null 2>&1; print AGENT-STARTED; exec cat",
        tmux_socket, rc_fixture,
    )
    assert screen.strip() == "", f"expected a blank pane, got {screen!r}"
    assert "AGENT-STARTED" not in screen


@requires_tmux
def test_the_new_prefix_lets_the_agent_start(tmux_socket, rc_fixture):
    screen = _run_pane(
        RC_SOURCE.replace("~/.zshrc", "{rc}") + "; print AGENT-STARTED; exec cat",
        tmux_socket, rc_fixture,
    )
    assert "AGENT-STARTED" in screen, screen
    assert "PROMPTED" not in screen, "rc must not have prompted at all"
    assert "BANNER-NOISE" not in screen, "rc chatter must still be suppressed"


@requires_tmux
def test_rc_exports_and_functions_survive_the_redirect(tmux_socket, rc_fixture):
    screen = _run_pane(
        RC_SOURCE.replace("~/.zshrc", "{rc}")
        + "; print FROM_RC=$FROM_RC; rc_defined_func; exec cat",
        tmux_socket, rc_fixture,
    )
    assert "FROM_RC=yes" in screen, screen
    assert "rc_defined_func ran" in screen, screen


@requires_tmux
def test_the_agent_still_gets_a_real_tty_on_stdin(tmux_socket, rc_fixture):
    screen = _run_pane(
        RC_SOURCE.replace("~/.zshrc", "{rc}")
        + '; if [[ -t 0 ]]; then print FD0=TTY; else print FD0=NOT-TTY; fi; exec cat',
        tmux_socket, rc_fixture,
    )
    assert "FD0=TTY" in screen, screen


@requires_tmux
def test_an_rc_that_reads_without_a_guard_fails_fast_instead_of_hanging(
    tmux_socket,
):
    path = Path(tempfile.gettempdir()) / f"cc_rc_blind_{uuid.uuid4().hex[:6]}.zsh"
    path.write_text('printf "blind prompt: "\nread -r R\nprint "rc=$?"\n')
    try:
        screen = _run_pane(
            "source {rc} </dev/null; print SURVIVED; exec cat", tmux_socket, path,
        )
    finally:
        path.unlink(missing_ok=True)
    assert "SURVIVED" in screen, screen
