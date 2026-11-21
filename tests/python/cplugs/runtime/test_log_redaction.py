
from __future__ import annotations

import asyncio
import string
from pathlib import Path
from typing import Any, Dict, List

from structlog.testing import capture_logs

from src.plugins.runtime import log_redaction
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens

FAKE_TOKEN = "ghp" + "_" + "".join(string.ascii_letters[(i * 7) % 52] for i in range(36))


def _dispatch_log(tmp_path: Path, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    dispatcher = HostDispatcher(HostServices(activity=lambda e: None), OwnerTokens(), home=tmp_path)
    ctx = PluginContext(plugin_id="clock", install_key="0" * 32, data_dir=tmp_path / "data", granted=frozenset())
    with capture_logs() as logs:
        asyncio.run(dispatcher.handle(ctx, "log", params))
    return logs


def test_log_notification_fields_are_redacted(tmp_path: Path) -> None:
    logs = _dispatch_log(tmp_path, {"level": "warning", "event": f"x{FAKE_TOKEN}",
                                    "fields": {"auth": f"bearer {FAKE_TOKEN}", FAKE_TOKEN: "k", "note": "plain words"}})
    entry = next(e for e in logs if e.get("cplug") == "clock")
    assert FAKE_TOKEN not in repr(entry)
    assert entry["fields"]["note"] == "plain words"
    assert entry["fields"]["auth"].startswith("bearer ****")


def test_stderr_lines_are_redacted_even_split_across_reads() -> None:
    log = log_redaction.StderrLog("clock")
    raw = f"starting up\ntoken={FAKE_TOKEN} loaded\n".encode()
    cut = raw.index(b"ghp") + 6
    with capture_logs() as logs:
        log.feed(raw[:cut])
        log.feed(raw[cut:])
        log.close()
    lines = [e["line"] for e in logs if e["event"] == log_redaction.STDERR_EVENT]
    assert lines[0] == "starting up"
    assert len(lines) == 2 and FAKE_TOKEN not in lines[1] and lines[1].startswith("token=****")
    assert FAKE_TOKEN.encode() not in bytes(log.kept)


def test_stderr_past_the_cap_is_dropped() -> None:
    log = log_redaction.StderrLog("clock")
    with capture_logs() as logs:
        log.feed(b"a" * log_redaction.STDERR_CAP)
        log.feed(b"\nlater line\n")
        log.close()
    assert len(log.kept) == log_redaction.STDERR_CAP
    assert not any(e.get("line") == "later line" for e in logs)


def test_process_drains_stderr_through_the_redacting_log() -> None:
    from types import SimpleNamespace  # noqa: PLC0415

    from src.plugins.runtime.process import PluginProcess  # noqa: PLC0415

    async def run() -> PluginProcess:
        spec = SimpleNamespace(ctx=SimpleNamespace(plugin_id="clock"))
        proc = PluginProcess(spec, None, None, "9.9.9", on_exit=None)  # type: ignore[arg-type]
        reader = asyncio.StreamReader()
        reader.feed_data(f"key {FAKE_TOKEN}\n".encode())
        reader.feed_eof()
        proc._proc = SimpleNamespace(stderr=reader)  # type: ignore[assignment]
        await proc._drain_stderr()
        return proc

    with capture_logs() as logs:
        proc = asyncio.run(run())
    lines = [e["line"] for e in logs if e["event"] == log_redaction.STDERR_EVENT]
    assert lines == ["key " + "*" * len(FAKE_TOKEN)]
    assert FAKE_TOKEN.encode() not in bytes(proc.stderr)
