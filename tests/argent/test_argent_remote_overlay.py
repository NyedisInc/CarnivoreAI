
from __future__ import annotations

import asyncio
import json

import pytest

from src.core.argent import overlay as argent_overlay
from src.core.hosts.remote_resume import respawn_remote
from src.core.sessions import launch_overlay
from tests.test_hosts_remote_sessions import HOST, TMUX, rig  # noqa: F401

KEY = "ark_FAKE_key_0123456789abcdef"
GATEWAY = "https://gw.example"
SHOW = 'echo "tether:${ANTHROPIC_BASE_URL:-none}:${ANTHROPIC_CUSTOM_HEADERS:+hdr}:${CARNIVORE_ARGENT_KEY:-nokey}"; exec /bin/sh\n'


class StubProvider:

    def __init__(self, key: str) -> None:
        self.key, self.prepared, self.contexts, self.confirmed = key, [], [], []

    async def prepare_host(self, host_key: str) -> None:
        self.prepared.append(host_key)

    def plan(self, harness, purpose, host_key="local"):
        return launch_overlay.OverlayPlan(preamble=argent_overlay.preamble(GATEWAY, ""), secret_name=argent_overlay.SECRET_NAME)

    def chain_plan(self, harness, purpose, route):
        return None

    async def materialize(self, plan, ctx):
        self.contexts.append(ctx)
        return launch_overlay.OverlayDelivery(secrets={plan.secret_name: self.key or plan.direct_value})

    async def confirm(self, session_ref: str) -> None:
        self.confirmed.append(session_ref)


def leaks(calls, key: str) -> bool:
    return key in json.dumps(calls)


async def screen(rig, name: str, want: str) -> str:
    text = ""
    for _ in range(100):
        _, text = await rig.far("capture-pane", "-p", "-t", f"={name}:")
        if want in text:
            return text
        await asyncio.sleep(0.1)
    return text


@pytest.fixture
def provider():
    holder = []

    def install(key: str) -> StubProvider:
        holder.append(StubProvider(key))
        launch_overlay.register(holder[-1])
        return holder[-1]

    yield install
    launch_overlay.register(None)


@pytest.mark.asyncio
async def test_a_far_create_is_tethered_by_stdin_and_a_peer_row_is_untouched(rig, provider):
    rig.fake.add_tool("claude", SHOW)
    rig.fake.add_tool("tmux", f'exec {TMUX} "$@"\n')
    (rig.fake.root / "home" / "proj").mkdir(exist_ok=True)
    stub = provider(KEY)
    far = await rig.mgr.create_session(session_id="ses_fx8tth1", working_dir="~/proj", auto_start_claude=True,
                                       project_name="fx8 tether", label="fx8", host_key=HOST)
    ref = f"remote:{HOST}:{far.tmux_session}"
    assert stub.prepared == [HOST] and stub.confirmed == [ref]
    assert stub.contexts[0].host_key == HOST and stub.contexts[0].session_ref == ref
    assert stub.contexts[0].settings_override is False
    text = await screen(rig, far.tmux_session, "tether:")
    assert f"tether:{GATEWAY}:hdr:nokey" in text, text
    assert not leaks(rig.fake.calls(), KEY), "the key rode an ssh argv"
    assert leaks([{"argv": ["ssh", "host", f"tmux set-environment K {KEY}"]}], KEY), "the scan cannot go red"

    seen = len(stub.contexts)
    with pytest.raises(ValueError):
        await respawn_remote(rig.mgr, "remote:peer-ab12:carnivore_other")
    assert len(stub.contexts) == seen and stub.confirmed == [ref]


@pytest.mark.asyncio
async def test_an_untethered_far_create_launches_exactly_as_before(rig, provider):
    rig.fake.add_tool("claude", SHOW)
    rig.fake.add_tool("tmux", f'exec {TMUX} "$@"\n')
    (rig.fake.root / "home" / "proj").mkdir(exist_ok=True)
    stub = provider("")
    far = await rig.mgr.create_session(session_id="ses_fx8dir1", working_dir="~/proj", auto_start_claude=True,
                                       project_name="fx8 direct", label="fx8", host_key=HOST)
    text = await screen(rig, far.tmux_session, "tether:")
    assert "tether:none::nokey" in text, text
    _, start = await rig.far("display-message", "-p", "-t", f"={far.tmux_session}:", "#{pane_start_command}")
    assert "CARNIVORE_ARGENT_KEY" not in start and "tmux show-environment" not in start
    assert stub.confirmed


@pytest.mark.asyncio
async def test_a_far_restart_takes_the_overlay_and_delivers_the_key_before_the_respawn(rig, provider):
    rig.fake.add_tool("claude", SHOW)
    rig.fake.add_tool("tmux", f'exec {TMUX} "$@"\n')
    (rig.fake.root / "home" / "proj").mkdir(exist_ok=True)
    stub = provider("")
    far = await rig.mgr.create_session(session_id="ses_fx8rst1", working_dir="~/proj", auto_start_claude=True,
                                       project_name="fx8 restart", label="fx8", host_key=HOST)
    await screen(rig, far.tmux_session, "tether:none")
    stub.key = KEY
    await rig.far("send-keys", "-t", f"={far.tmux_session}:", "exit", "Enter")
    for _ in range(50):
        _, dead = await rig.far("display-message", "-p", "-t", f"={far.tmux_session}:", "#{pane_dead}")
        if dead.strip() == "1":
            break
        await asyncio.sleep(0.1)
    result = await respawn_remote(rig.mgr, f"remote:{HOST}:{far.tmux_session}")
    assert result["ok"], result
    text = await screen(rig, far.tmux_session, f"tether:{GATEWAY}")
    assert f"tether:{GATEWAY}:hdr:nokey" in text, text
    assert len(stub.contexts) == 2 and stub.confirmed[-1] == f"remote:{HOST}:{far.tmux_session}"
    assert not leaks(rig.fake.calls(), KEY), "the key rode an ssh argv"
