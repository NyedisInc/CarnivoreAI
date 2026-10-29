"""The conformance kit (``docs/cplug-platform.md`` 13.3): one probe per host rule, each able to go red.

A probe drives a :class:`Harness` with the hostile input of its finding and returns the list of ways the host failed (empty
means the rule holds). Every probe also runs a POSITIVE control (the legitimate call must still work), so a host that refuses
everything does not pass by looking at nothing (CLAUDE.md, gotcha 11). The negative control for a rule is the same probe run
against a deliberately permissive harness; the tests keep those next to the probes (``tests/python/cplugs/runtime``).

``real_harness`` wires the production code. The sandbox probe of 6.6 needs ``sandbox-exec`` and a real plugin process, so it is
a fixture plugin run by ``tests/python/cplugs/runtime/test_sandbox_e2e.py`` on macOS.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Tuple

import subprocess

from src.cplugs.runtime import frames, fsguard, git_ops, guards, index_expiry, sandbox, watchdog, webhooks
from src.cplugs.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.cplugs.runtime.owner_tokens import OwnerTokens
from src.cplugs.runtime.process import PluginSpec
from src.cplugs.runtime.supervisor import Supervisor

Probe = Callable[["Harness"], Awaitable[List[str]]]

PINNED_SESSION_FIELDS = frozenset({"id", "session_row_id", "label", "project_id", "activity_status", "unread", "startup_gate",
                                   "agent_family", "created_at", "last_activity"})
def _row(ident: str, host_key: str = "local", **wrapper: Any) -> Dict[str, Any]:
    from src.models.sessions import Session, SessionInfo  # noqa: PLC0415

    info = SessionInfo(session=Session(id=ident, working_dir="/Users/a/p"), host_key=host_key, **wrapper)
    return info.model_dump()


ROWS: List[Dict[str, Any]] = [
    _row("ses_ok", session_row_id=1, label="ok", project_id=2, agent_family="claude", agent_wrapper_label="claude",
         launched_with={"permissions": "default"}, claude_title="SECRET PLAN"),
    _row("ses_bypass", label="b", launched_with={"permissions": "bypassPermissions"}),
    _row("ses_adopted", label="adopted", launched_with=None),
    _row("ses_live", label="live", launched_with={"permissions": "default"}),
    _row("remote:peer-ab:ses_9", host_key="peer-ab", label="far", launched_with={"permissions": "default"}),
]
LIVE_MODES: Dict[str, str] = {"ses_live": "bypass permissions on"}


@dataclass
class Harness:

    handle: Callable[[PluginContext, str, Any], Awaitable[Any]]
    mint: Callable[[PluginContext, str], str]
    ctx: Callable[..., PluginContext]
    pin_tools: Callable[[List[Mapping[str, Any]], Any], None]
    new_guard: Callable[[], Any]
    new_splitter: Callable[[], Any]
    open_nofollow: Callable[[Path, str], int]
    git_argv: Callable[[Path, str], List[str]]
    git_env: Callable[[], Dict[str, str]]
    git_read: Callable[[Path, str], Any]
    git_snapshot: Callable[[Path, str], Any]
    new_verifier: Callable[[Callable[[], float]], Any]
    index_may_run: Callable[[Optional[Mapping[str, Any]], bool], bool]
    check_memory: Callable[..., watchdog.Verdict]
    check_disk: Callable[..., watchdog.Verdict]
    render_profile: Callable[[sandbox.Layout], str]
    revoke: Callable[[str], Awaitable[Dict[str, Any]]]
    safe_mode_admit: Callable[[], Optional[str]]
    tmp: Path
    alerts: List[Tuple[str, str, str, str]] = field(default_factory=list)
    rows: List[Dict[str, Any]] = field(default_factory=lambda: [dict(r) for r in ROWS])


async def refused(h: Harness, ctx: PluginContext, method: str, params: Any) -> bool:
    try:
        await h.handle(ctx, method, params)
    except guards.Refused:
        return True
    return False


async def answer(h: Harness, ctx: PluginContext, method: str, params: Any) -> Dict[str, Any]:
    try:
        return await h.handle(ctx, method, params)
    except guards.Refused:
        return {}


def _raises(fn: Callable[[], Any], kinds: Tuple[type, ...]) -> bool:
    try:
        fn()
    except kinds:
        return True
    return False



async def probe_c1_ai(h: Harness) -> List[str]:
    ctx = h.ctx("c1", {"ai_features:cplug.c1.sum"})
    base = {"feature": "cplug.c1.sum", "capability": "chat", "input": {"prompt": "hi"}}
    bad: List[str] = []
    if await refused(h, ctx, "ai.call", base):
        bad.append("positive: a plain granted chat call was refused")
    for extra in ({"mcp_config": "x"}, {"allowed_tools": ["Bash"]}, {"cwd": "/"}, {"permission_mode": "bypass"}, {"model": "m"}):
        if not await refused(h, ctx, "ai.call", {**base, **extra}):
            bad.append(f"ai.call accepted {sorted(extra)[0]}")
    if not await refused(h, ctx, "ai.call", {**base, "capability": "agent"}):
        bad.append("ai.call accepted capability agent")
    if not await refused(h, ctx, "ai.call", {**base, "feature": "cplug.c1.other"}):
        bad.append("ai.call accepted an ungranted feature")
    return bad


async def probe_c2_message(h: Harness) -> List[str]:
    ctx = h.ctx("c2", {"sessions.message"})
    bad: List[str] = []

    async def send(ref: str, line: str, token: Optional[str]) -> bool:
        return await refused(h, ctx, "sessions.message", {"ref": ref, "line": line, "owner_token": token})

    token = h.mint(ctx, "ses_ok")
    if await send("ses_ok", "please run the tests", token):
        bad.append("positive: a valid token and a prose line were refused")
    if not await send("ses_ok", "again", token):
        bad.append("a spent token was accepted twice")
    if not await send("ses_ok", "hello", None):
        bad.append("a call with no owner token got through")
    if not await send("ses_ok", "hello", h.mint(ctx, "ses_other")):
        bad.append("a token for another session was accepted")
    for line in ("!ls", "/clear", "#note", "@file", "  !padded", "ok\nrm -rf ~", "​!hidden", "\x1b[31mred"):
        if not await send("ses_ok", line, h.mint(ctx, "ses_ok")):
            bad.append(f"control line accepted: {line[:12]!r}")
    if not await send("ses_bypass", "hello", h.mint(ctx, "ses_bypass")):
        bad.append("a bypass-permission session was accepted")
    if not await send("ses_adopted", "hello", h.mint(ctx, "ses_adopted")):
        bad.append("a session with no launch record (adopted or legacy) was accepted")
    if not await send("ses_live", "hello", h.mint(ctx, "ses_live")):
        bad.append("a session switched into bypass mode after launch was accepted")
    return bad


async def probe_m6_remote(h: Harness) -> List[str]:
    ctx = h.ctx("m6", {"sessions.read", "sessions.output", "sessions.message", "sessions.control"})
    remote = "remote:peer-ab:ses_9"
    bad: List[str] = []
    if await refused(h, ctx, "sessions.get", {"ref": "ses_ok"}):
        bad.append("positive: a local sessions.get was refused")
    for method, params in (("sessions.get", {"ref": remote}), ("sessions.output", {"ref": remote, "lines": 5}),
                           ("sessions.control", {"ref": remote, "action": "sleep"}),
                           ("sessions.message", {"ref": remote, "line": "hi", "owner_token": h.mint(ctx, remote)})):
        if not await refused(h, ctx, method, params):
            bad.append(f"{method} accepted a remote ref")
    listed = await answer(h, ctx, "sessions.list", {})
    rows = listed.get("sessions", [])
    if any(str(r.get("id", "")).startswith("remote:") or "session" in r for r in rows):
        bad.append("sessions.list returned a remote row")
    if not any(r.get("id") == "ses_ok" for r in rows):
        bad.append("positive: sessions.list lost the local row's id (it lives on the nested .session)")
    return bad


async def probe_h4_fields(h: Harness) -> List[str]:
    ctx = h.ctx("h4", {"sessions.read"})
    out = await answer(h, ctx, "sessions.list", {})
    extra = {k for row in out.get("sessions", []) for k in row} - PINNED_SESSION_FIELDS
    bad = [f"field leaked: {k}" for k in sorted(extra)]
    if not any(r.get("id") == "ses_ok" and r.get("created_at") for r in out.get("sessions", [])):
        bad.append("positive: no addressable row came back (id and created_at come from the nested .session)")
    return bad


async def probe_h5_tools(h: Harness) -> List[str]:
    manifest = [{"name": "a", "description": "d", "inputSchema": {"type": "object"}, "gate": "read"}]
    bad: List[str] = []
    if _raises(lambda: h.pin_tools(manifest, {"tools": [dict(reversed(list(manifest[0].items())))]}), (guards.Refused,)):
        bad.append("positive: the same tool in another key order was refused")
    for label, runtime in (("changed description", {"tools": [{**manifest[0], "description": "do evil"}]}),
                           ("extra tool", {"tools": manifest + [{"name": "b"}]}), ("no tools", {"tools": []}),
                           ("garbage", "tools")):
        if not _raises(lambda r=runtime: h.pin_tools(manifest, r), (guards.Refused,)):
            bad.append(f"tools/list accepted: {label}")
    return bad


async def probe_l3_frames(h: Harness) -> List[str]:
    bad: List[str] = []
    ok = b'{"jsonrpc":"2.0","id":%d,"method":"ping","params":{}}'
    guard = h.new_guard()
    if _raises(lambda: guard.parse(ok % 5), (frames.FrameViolation,)):
        bad.append("positive: a valid request was refused")
    if not _raises(lambda: guard.parse(ok % 5), (frames.FrameViolation,)):
        bad.append("a duplicate request id was accepted")
    if not _raises(lambda: guard.parse(ok % 3), (frames.FrameViolation,)):
        bad.append("an out-of-order request id was accepted")
    if not _raises(lambda: h.new_guard().parse(b'{"jsonrpc":"2.0","id":9,"result":{}}'), (frames.FrameViolation,)):
        bad.append("an unsolicited response was accepted")
    if not _raises(lambda: h.new_guard().parse(b'{"jsonrpc":"2.0","method":"log","method":"x"}'), (frames.FrameViolation,)):
        bad.append("a duplicate JSON key was accepted")
    if not _raises(lambda: h.new_guard().parse(b'{"jsonrpc":"2.0","method":"m","params":' + b"[" * 200 + b"]" * 200 + b"}"),
                   (frames.FrameViolation,)):
        bad.append("a deeply nested frame was accepted")
    if not _raises(lambda: h.new_splitter().feed(b"x" * (frames.MAX_FRAME_BYTES + 10)), (frames.FrameViolation,)):
        bad.append("an over-long unterminated line was buffered")
    flood = h.new_guard()
    note = b'{"jsonrpc":"2.0","method":"log","params":{}}'

    def spam() -> None:
        for _ in range(frames.NOTIFICATIONS_PER_SECOND + 5):
            flood.parse(note)

    if not _raises(spam, (frames.FrameViolation,)):
        bad.append("a notification flood was accepted")
    return bad


async def probe_h6_files(h: Harness) -> List[str]:
    bad: List[str] = []
    files, outside = h.tmp / "h6" / "files", h.tmp / "h6" / "outside"
    files.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "secret.txt").write_text("db")
    (files / "plain.txt").write_text("ok")
    for name, target in (("link", outside / "secret.txt"), ("dirlink", outside)):
        if not (files / name).is_symlink():
            os.symlink(target, files / name)
    try:
        os.close(h.open_nofollow(files, "plain.txt"))
    except (OSError, fsguard.UnsafePath):
        bad.append("positive: a plain file could not be opened")
    for rel in ("link", "dirlink/secret.txt", "../outside/secret.txt"):
        if not _raises(lambda r=rel: os.close(h.open_nofollow(files, r)), (OSError, fsguard.UnsafePath)):
            bad.append(f"opened through {rel}")
    ctx = h.ctx("h6", {"exports.write"})
    folder = str(h.tmp / "exports")
    payload = base64.b64encode(b"hello").decode()
    if await refused(h, ctx, "exports.write", {"folder": folder, "name": "good.txt", "bytes": payload}):
        bad.append("positive: a valid export was refused")
    for name in (".bashrc", "../x", "a/b", "x" * 200, ""):
        if not await refused(h, ctx, "exports.write", {"folder": folder, "name": name, "bytes": payload}):
            bad.append(f"export name accepted: {name[:12]!r}")
    for folder_bad in (str(h.tmp / "home"), str(h.tmp / "home" / "Library"), str(h.tmp), "/etc", "/Applications"):
        if not await refused(h, ctx, "exports.write", {"folder": folder_bad, "name": "n.txt", "bytes": payload}):
            bad.append(f"export folder accepted: {folder_bad}")
    return bad


async def probe_m1_notify(h: Harness) -> List[str]:
    ctx = h.ctx("m1", {"notify"})
    bad: List[str] = []
    for title in ("see https://evil.example/x", "go to example.net now", "go to evil.ru now", "login at bank-secure.tk",
                  "visit evil\uff0ecom now", "visit evil\u3002xyz now"):
        if not await refused(h, ctx, "notify.toast", {"ref": "ses_ok", "title": title}):
            bad.append(f"toast with URL text accepted: {title[:20]}")
    for n in range(6):
        if await refused(h, ctx, "notify.toast", {"ref": "ses_ok", "title": f"build {n} done"}):
            bad.append("positive: a plain toast was refused")
            break
    if not await refused(h, ctx, "notify.toast", {"ref": "ses_ok", "title": "one more"}):
        bad.append("a 7th toast in an hour was accepted")
    if not await refused(h, ctx, "notify.alert", {"key": "Bad Key!", "severity": "info", "title": "t"}):
        bad.append("an alert key outside ^[a-z0-9_]{1,32}$ was accepted")
    before = len(h.alerts)
    await refused(h, ctx, "notify.alert", {"key": "crash_loop", "severity": "error", "title": "spoof"})
    new = h.alerts[before:]
    if not new:
        bad.append("positive: a plain alert was not raised")
    bad.extend(f"alert raised under a host key: {k}" for _, k, _, _ in new if not k.startswith("cplug.m1.p."))
    return bad


async def probe_l2_git(h: Harness) -> List[str]:
    bad: List[str] = []
    argv = h.git_argv(h.tmp, "status")
    for need in ("core.fsmonitor=false", "core.hooksPath=/dev/null", "--no-pager"):
        if need not in argv:
            bad.append(f"git argv lacks {need}")
    if "--no-ext-diff" not in h.git_argv(h.tmp, "diff_names"):
        bad.append("git diff lacks --no-ext-diff")
    if h.git_env().get("GIT_CONFIG_NOSYSTEM") != "1":
        bad.append("git env lacks GIT_CONFIG_NOSYSTEM=1")
    if not _raises(lambda: h.git_argv(h.tmp, "log -p"), (git_ops.GitRefused,)):
        bad.append("an unknown git op was accepted")
    repo, marker = h.tmp / "l2repo", h.tmp / "l2-filter-ran"
    clean = h.tmp / "l2clean"
    for folder in (repo, clean):
        _make_repo(folder)
    if _raises(lambda: h.git_read(clean, "status"), (git_ops.GitRefused,)):
        bad.append("positive: status on a plain repo was refused")
    _git(repo, "config", "filter.evil.clean", f"sh -c 'touch {marker}; cat'")
    (repo / "a.txt").write_text("changed\n")
    for label, call in (("status", lambda: h.git_read(repo, "status")), ("diff_names", lambda: h.git_read(repo, "diff_names")),
                        ("snapshot", lambda: h.git_snapshot(repo, "t1"))):
        if not _raises(call, (git_ops.GitRefused,)):
            bad.append(f"git {label} ran on a repo whose config names a filter driver")
    if marker.exists():
        bad.append("a repo-config filter driver RAN as the owner")
    return bad


def _git(repo: Path, *args: str) -> None:
    env = {"PATH": "/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "HOME": "/var/empty",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["/usr/bin/git", "-C", str(repo), *args], env=env, check=True, capture_output=True, timeout=20)


def _make_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("original\n")
    (repo / ".gitattributes").write_text("*.txt filter=evil\n")
    _git(repo, "add", "a.txt", ".gitattributes")
    _git(repo, "commit", "-q", "-m", "x")


async def probe_l4_webhooks(h: Harness) -> List[str]:
    bad: List[str] = []
    now = [1_000_000.0]
    verifier = h.new_verifier(lambda: now[0])
    secret = b"s3cret-s3cret-s3cret"

    def hdr(ts: int, nonce: str, body: bytes, key: bytes = secret) -> Dict[str, str]:
        return {"x-timestamp": str(ts), "x-nonce": nonce, "x-signature": webhooks.sign(key, ts, nonce, body)}

    def verify(hook: str, headers: Dict[str, str], body: bytes) -> None:
        verifier.verify(hook, secret, headers, body)

    body = b'{"a":1}'
    if _raises(lambda: verify("h", hdr(1_000_000, "n1", body), body), (webhooks.WebhookRefused,)):
        bad.append("positive: a valid webhook was refused")
    if not _raises(lambda: verify("h", hdr(1_000_000, "n1", body), body), (webhooks.WebhookRefused,)):
        bad.append("a replayed nonce was accepted")
    if not _raises(lambda: verify("h", hdr(1_000_000 - 400, "n2", body), body), (webhooks.WebhookRefused,)):
        bad.append("a stale timestamp was accepted")
    if not _raises(lambda: verify("h", hdr(1_000_000, "n3", body, b"wrong"), body), (webhooks.WebhookRefused,)):
        bad.append("a bad signature was accepted")
    if not _raises(lambda: verifier.verify("h", b"", hdr(1_000_000, "n5", body, b""), body), (webhooks.WebhookRefused,)):
        bad.append("an empty secret was accepted (HMAC with an empty key is forgeable)")
    if not _raises(lambda: verify("h", {**hdr(1_000_000, "n6", body), "x-signature": "\u00e9"}, body), (webhooks.WebhookRefused,)):
        bad.append("a non-ASCII signature header was not refused as bad_signature")
    big = b"x" * (webhooks.MAX_BODY_BYTES + 1)
    if not _raises(lambda: verify("h", hdr(1_000_000, "n4", big), big), (webhooks.WebhookRefused,)):
        bad.append("an oversized body was accepted")

    def storm() -> None:
        for i in range(webhooks.PER_HOOK_PER_MINUTE + 5):
            verify("busy", hdr(1_000_000, f"s{i}", body), body)

    if not _raises(storm, (webhooks.WebhookRefused,)):
        bad.append("a webhook storm was accepted")
    return bad


async def probe_h9_index(h: Harness) -> List[str]:
    bad: List[str] = []
    if not h.index_may_run({"expires_at": "2999-01-01T00:00:00Z"}, False):
        bad.append("positive: a fresh index was refused")
    if h.index_may_run({"expires_at": "2000-01-01T00:00:00Z"}, False):
        bad.append("an expired index let a third-party plugin run")
    if h.index_may_run(None, False) or h.index_may_run({"expires_at": "garbage"}, False):
        bad.append("a missing or unreadable index let a third-party plugin run")
    if not h.index_may_run({"expires_at": "2000-01-01T00:00:00Z"}, True):
        bad.append("the owner's per-plugin override was ignored")
    return bad


async def probe_m4_limits(h: Harness) -> List[str]:
    bad: List[str] = []
    if not h.check_memory(watchdog.Usage(10 * 2**20, 0.0)).ok:
        bad.append("positive: 10 MiB tripped the memory watchdog")
    if h.check_memory(watchdog.Usage(600 * 2**20, 0.0)).ok:
        bad.append("600 MiB did not trip the memory watchdog")
    files, outside = h.tmp / "m4" / "files", h.tmp / "m4" / "outside"
    files.mkdir(parents=True, exist_ok=True)
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "big").write_bytes(b"x" * 5000)
    if not (files / "ln").is_symlink():
        os.symlink(outside / "big", files / "ln")
    if not h.check_disk(files, 1000).ok:
        bad.append("positive: a symlink to a big file was counted as its target")
    (files / "fat").write_bytes(b"x" * 2000)
    if h.check_disk(files, 1000).ok:
        bad.append("a folder over its quota did not trip")
    return bad


async def probe_h7_profile(h: Harness) -> List[str]:
    home, app, state = h.tmp / "home", h.tmp / "app", h.tmp / "home" / "state"
    layout = sandbox.Layout(interpreter=h.tmp / "fw" / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python",
                            stdlib_root=h.tmp / "fw", runtime_dir=state / "cplug-runtime" / "1.0",
                            code_dir=state / "cplugs" / "k" / "code", data_dir=state / "cplugs" / "k")
    text = h.render_profile(layout)
    bad: List[str] = []
    readable = [ln for ln in text.splitlines() if ln.startswith("(allow file-read*")]
    granted = [Path(p) for ln in readable for p in _subpaths(ln)]
    if str(layout.runtime_dir) not in [str(p) for p in granted]:
        bad.append("positive: the runtime copy is not readable")
    for label, forbidden in (("app root", app), ("state folder", state), ("home folder", home)):
        if any(p == forbidden or p in forbidden.parents for p in granted):
            bad.append(f"profile makes the {label} readable")
    for need in ("(deny network*)", "(deny process-fork)", "(deny default)", '(deny sysctl-read (sysctl-name-prefix "kern.proc."))'):
        if need not in text:
            bad.append(f"profile lacks {need}")
    return bad


def _subpaths(line: str) -> List[str]:
    out, rest = [], line
    while '(subpath "' in rest:
        rest = rest.split('(subpath "', 1)[1]
        out.append(rest.split('"', 1)[0])
    return out


async def probe_l5_revocation(h: Harness) -> List[str]:
    result = await h.revoke("l5plug")
    bad: List[str] = []
    if "revoked" not in [key for _, key, _ in result["alerts"]]:
        bad.append("no revoked alert was raised")
    if "l5plug" not in result["cancelled"]:
        bad.append("pending inbox items, timers and routes were not cancelled")
    if result["state"] != "revoked":
        bad.append("the plugin is not in the revoked state")
    if result["respawn_refusal"] != "revoked":
        bad.append("a revoked plugin may respawn")
    return bad


async def probe_safe_mode(h: Harness) -> List[str]:
    return [] if h.safe_mode_admit() == "safe_mode" else ["safe mode admitted a third-party plugin"]


RULES: Tuple[Tuple[str, str, Probe], ...] = (
    ("c1_ai_call", "C1", probe_c1_ai), ("c2_owner_token_and_control_lines", "C2", probe_c2_message),
    ("m6_remote_refs", "M6", probe_m6_remote), ("h4_session_fields", "H4", probe_h4_fields),
    ("h5_pinned_tools", "H5", probe_h5_tools), ("l3_frame_hardening", "L3", probe_l3_frames),
    ("h6_files_and_exports", "H6", probe_h6_files), ("m1_notify", "M1", probe_m1_notify),
    ("l2_git_flags", "L2", probe_l2_git), ("l4_webhooks", "L4", probe_l4_webhooks),
    ("h9_index_expiry", "H9", probe_h9_index), ("m4_limits", "M4", probe_m4_limits),
    ("h7_profile", "H7", probe_h7_profile), ("l5_revocation", "L5", probe_l5_revocation),
    ("safe_mode", "6.7", probe_safe_mode),
)


async def run_all(h: Harness) -> Dict[str, List[str]]:
    return {rule: await probe(h) for rule, _, probe in RULES}



def real_harness(tmp: Path) -> Harness:
    (tmp / "home").mkdir(parents=True, exist_ok=True)
    (tmp / "exports").mkdir(parents=True, exist_ok=True)
    holder: Dict[str, Any] = {"alerts": []}
    rows: List[Dict[str, Any]] = [dict(r) for r in ROWS]
    log: List[Dict[str, Any]] = []

    async def list_sessions() -> List[Dict[str, Any]]:
        return rows

    async def get_session(ref: str) -> Optional[Dict[str, Any]]:
        return next((dict(r) for r in rows if r["session"]["id"] == ref), None)

    async def permission_mode(ref: str) -> Optional[str]:
        return LIVE_MODES.get(ref, "default")

    async def paste_line(ref: str, line: str) -> Dict[str, Any]:
        return {"delivered": True}

    class _Ai:
        async def call(self, feature: str, capability: str, input: Mapping[str, Any]) -> Dict[str, Any]:
            return {"output": "ok"}

    services = HostServices(
        activity=log.append, list_sessions=list_sessions, get_session=get_session, permission_mode=permission_mode, paste_line=paste_line,
        ai_for=lambda ctx: _Ai(), toast=lambda *a: None,
        alert=lambda pid, key, sev, title, params: holder["alerts"].append((pid, key, sev, title)),
        session_output=None)
    tokens = OwnerTokens()
    dispatcher = HostDispatcher(services, tokens, home=tmp / "home")
    recorded: Dict[str, List[Any]] = {"alerts": [], "cancelled": []}
    sup_cfg = dict(state_dir=tmp / "state", app_version="1.0", dispatcher=dispatcher,
                   alert=lambda pid, key, why: recorded["alerts"].append((pid, key, why)),
                   cancel_side_effects=lambda pid: recorded["cancelled"].append(pid) or {"inbox": 0, "timers": 0, "routes": 0},
                   activity=log.append)

    def spec(plugin_id: str) -> PluginSpec:
        return PluginSpec(ctx=make_ctx(plugin_id, set()), code_dir=tmp, entry="main")

    def make_ctx(plugin_id: str, granted: Any, **kw: Any) -> PluginContext:
        (tmp / "home" / "Library").mkdir(parents=True, exist_ok=True)
        picked = (tmp / "exports", tmp / "home", tmp / "home" / "Library", Path("/etc"), Path("/Applications"))
        return PluginContext(plugin_id=plugin_id, install_key="0" * 32, data_dir=tmp / "data" / plugin_id,
                             granted=frozenset(granted), picked_folders=picked, **kw)

    async def revoke(plugin_id: str) -> Dict[str, Any]:
        sup = Supervisor(**sup_cfg, index={"expires_at": "2999-01-01T00:00:00Z"})
        await sup.revoke(plugin_id)
        return {"alerts": recorded["alerts"], "cancelled": recorded["cancelled"], "state": sup.state(plugin_id),
                "respawn_refusal": sup.admit(spec(plugin_id))}

    def safe_mode_admit() -> Optional[str]:
        return Supervisor(**sup_cfg, safe_mode=True).admit(spec("safe"))

    return Harness(
        handle=dispatcher.handle, mint=lambda ctx, ref: tokens.mint(ctx.install_key, ref), ctx=make_ctx,
        pin_tools=guards.pin_tools, new_guard=frames.FrameGuard, new_splitter=frames.LineSplitter,
        open_nofollow=lambda root, rel: fsguard.open_contained(root, rel, os.O_RDONLY),
        git_argv=git_ops.read_argv, git_env=git_ops.git_env, git_read=git_ops.read, git_snapshot=git_ops.snapshot, new_verifier=lambda clock: webhooks.InboundVerifier(clock),
        index_may_run=lambda index, override: index_expiry.may_run_third_party(index_expiry.index_state(index), override),
        check_memory=watchdog.check_memory, check_disk=watchdog.check_disk, render_profile=sandbox.render_profile,
        revoke=revoke, safe_mode_admit=safe_mode_admit, tmp=tmp, alerts=holder["alerts"], rows=rows)
