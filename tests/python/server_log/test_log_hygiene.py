
from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path

import pytest
import structlog

from src.core.server_log import breadcrumb, locate, redact

TOKEN = "ghp_" + "a1B2c3D4e5" * 3 + "a1B2c3"


def _render(processor, **event) -> dict:
    line = structlog.processors.JSONRenderer()(None, "info", processor(None, "info", dict(event)))
    return json.loads(line)


def test_token_shaped_value_is_masked_in_emitted_json() -> None:
    out = _render(redact.redact_event, event="auth_header_seen", level="info", header=f"Bearer {TOKEN}",
                  nested={"list": [TOKEN, 3]}, count=2)
    text = json.dumps(out)
    assert TOKEN not in text
    assert out["event"] == "auth_header_seen" and out["count"] == 2 and out["level"] == "info"
    assert out["header"].startswith("Bearer ") and len(out["header"]) == len(f"Bearer {TOKEN}")


def test_multiline_value_is_masked_too() -> None:
    out = _render(redact.redact_event, event="crash", exception=f"Traceback\n  token={TOKEN}\nValueError")
    assert TOKEN not in out["exception"] and out["exception"].startswith("Traceback\n")


def test_a_redactor_that_raises_replaces_the_event() -> None:
    def broken(_text: str) -> str:
        raise RuntimeError("detector exploded")

    out = _render(redact.make_processor(broken), event=f"leak {TOKEN}", level="error", timestamp="2026-10-16T00:00:00Z")
    assert out == {"event": redact.FAILED_EVENT, "error_type": "RuntimeError", "level": "error",
                   "timestamp": "2026-10-16T00:00:00Z"}


def test_stars_never_leak_from_one_field_onto_the_next() -> None:
    out = _render(redact.redact_event, token=TOKEN, event="smoke", after="plain")
    assert out["token"] == "*" * len(TOKEN)
    assert (out["event"], out["after"]) == ("smoke", "plain")


_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _uvicorn_logger_state() -> list:
    return [(name, list(lg.handlers), lg.propagate, lg.level, lg.disabled)
            for name in _UVICORN_LOGGERS for lg in (logging.getLogger(name),)]


@pytest.fixture
def production_uvicorn_loggers():
    saved = _uvicorn_logger_state()
    for name in _UVICORN_LOGGERS:
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
        lg.disabled = False
    yield
    for name, handlers, propagate, level, disabled in saved:
        lg = logging.getLogger(name)
        lg.handlers[:] = handlers
        lg.propagate, lg.level, lg.disabled = propagate, level, disabled


def test_the_in_process_listeners_leave_uvicorn_logging_alone(production_uvicorn_loggers) -> None:
    import ssl
    import tempfile

    from src.core.federation.peer_listener import PeerListener
    from src.core.phone_link.listener import LoopbackListener

    before = _uvicorn_logger_state()
    LoopbackListener(lambda scope, receive, send: None, ssl.create_default_context(ssl.Purpose.CLIENT_AUTH))
    PeerListener(lambda scope, receive, send: None, tempfile.gettempdir() + "/peer.sock")
    after = _uvicorn_logger_state()
    assert [(n, h) for n, h, *_ in after] == [(n, h) for n, h, *_ in before]
    assert all(p for n, _, p, *_ in after if n != "uvicorn.access")


def test_stdlib_and_uvicorn_records_take_the_same_chain(production_uvicorn_loggers) -> None:
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    stream = io.StringIO()
    try:
        redact.install_stdlib_routing(stream)
        uvicorn_logger = logging.getLogger("uvicorn.error")
        uvicorn_logger.setLevel(logging.INFO)
        uvicorn_logger.info("Application startup complete.")
        root.setLevel(logging.INFO)
        logging.getLogger("httpx").info("HTTP Request: GET /poll")
        logging.getLogger("some.library").warning("calling with %s", TOKEN)
        try:
            raise ValueError(f"boom {TOKEN}")
        except ValueError:
            logging.getLogger("some.library").exception("failed")
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        for handler in saved_handlers:
            root.addHandler(handler)
        root.setLevel(saved_level)
        logging.getLogger("uvicorn.error").setLevel(logging.NOTSET)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert [line["event"] for line in lines][:2] == ["Application startup complete.", "calling with " + "*" * len(TOKEN)]
    assert TOKEN not in stream.getvalue()
    assert lines[2]["level"] == "error" and "ValueError: boom" in lines[2]["exception"]




@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("CARNIVORE_LOG_FILE", "CLOUDE_LOG_FILE", "CLOUDECODE_LOG_FILE"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "Library" / "Logs" / locate.LAUNCHD_LOG_DIR_NAME).mkdir(parents=True)
    (tmp_path / "state").mkdir(mode=0o700)
    locate.own_log_path.cache_clear()
    yield tmp_path
    locate.own_log_path.cache_clear()


def _launchd_log(home: Path) -> Path:
    path = home / "Library" / "Logs" / locate.LAUNCHD_LOG_DIR_NAME / locate.LAUNCHD_LOG_FILE_NAME
    path.write_text("{}\n")
    return path


def _live_lstarts(pids):
    return {pid: "Fri Oct 16 10:00:00 2026" for pid in pids}


def test_route_path_comes_from_memory_never_from_the_breadcrumb(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = _launchd_log(home)
    monkeypatch.setenv("CARNIVORE_LOG_FILE", str(log))
    assert locate.server_log_path() == log
    (home / "state" / breadcrumb.BREADCRUMB_NAME).write_text(json.dumps({"path": "/etc/passwd", "pid": 1}))
    assert locate.server_log_path() == log


def test_env_path_outside_the_allow_list_is_refused(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CARNIVORE_LOG_FILE", str(home / "elsewhere" / locate.LAUNCHD_LOG_FILE_NAME))
    assert locate.own_log_path() is None
    assert locate.server_log_path() == locate.default_log_path()


def test_publish_writes_a_private_breadcrumb_that_reads_back_live(home: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    log = _launchd_log(home)
    monkeypatch.setenv("CARNIVORE_LOG_FILE", str(log))
    written = breadcrumb.publish(home / "state", lstarts=_live_lstarts)
    assert written is not None and (os.stat(written).st_mode & 0o777) == 0o600
    data = json.loads(written.read_text())
    assert data == {"path": str(log), "pid": os.getpid(), "started_at": "Fri Oct 16 10:00:00 2026",
                    "writer": os.getppid()}
    located = breadcrumb.read_breadcrumb(home / "state", lstarts=_live_lstarts)
    assert located.path == log and located.status == breadcrumb.LIVE


def test_publish_writes_nothing_without_a_launcher_log(home: Path) -> None:
    assert breadcrumb.publish(home / "state", lstarts=_live_lstarts) is None
    with pytest.raises(breadcrumb.BreadcrumbMissing):
        breadcrumb.read_breadcrumb(home / "state")


def _plant(home: Path, path: str, **extra) -> None:
    target = home / "state" / breadcrumb.BREADCRUMB_NAME
    target.write_text(json.dumps({"path": path, "pid": os.getpid(), "started_at": "x", "writer": 1, **extra}))
    target.chmod(0o600)


def test_poisoned_breadcrumb_symlinked_log_is_refused(home: Path, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    link = home / "Library" / "Logs" / locate.LAUNCHD_LOG_DIR_NAME / locate.LAUNCHD_LOG_FILE_NAME
    link.symlink_to(secret)
    _plant(home, str(link))
    with pytest.raises(breadcrumb.BreadcrumbRefused) as caught:
        breadcrumb.read_breadcrumb(home / "state", lstarts=_live_lstarts)
    assert caught.value.reason == "log_symlink"


@pytest.mark.parametrize("name", ["passwd", "launchd.log.1", "server.log", "launchd.log/../launchd.log"])
def test_poisoned_breadcrumb_wrong_basename_is_refused(home: Path, name: str) -> None:
    _launchd_log(home)
    _plant(home, str(home / "Library" / "Logs" / locate.LAUNCHD_LOG_DIR_NAME / name))
    with pytest.raises(breadcrumb.BreadcrumbRefused) as caught:
        breadcrumb.read_breadcrumb(home / "state", lstarts=_live_lstarts)
    assert caught.value.reason == "log_path_not_allowed"


def test_poisoned_breadcrumb_outside_the_log_dirs_is_refused(home: Path) -> None:
    outside = home / "Documents" / "server.log"
    outside.parent.mkdir()
    outside.write_text("{}\n")
    _plant(home, str(outside))
    with pytest.raises(breadcrumb.BreadcrumbRefused) as caught:
        breadcrumb.read_breadcrumb(home / "state", lstarts=_live_lstarts)
    assert caught.value.reason == "log_path_not_allowed"


def test_a_symlinked_breadcrumb_is_refused(home: Path) -> None:
    real = home / "planted.json"
    real.write_text(json.dumps({"path": str(_launchd_log(home)), "pid": os.getpid()}))
    (home / "state" / breadcrumb.BREADCRUMB_NAME).symlink_to(real)
    with pytest.raises(breadcrumb.BreadcrumbRefused) as caught:
        breadcrumb.read_breadcrumb(home / "state", lstarts=_live_lstarts)
    assert caught.value.reason == "breadcrumb_symlink"


def test_a_dead_or_recycled_writer_is_labeled_stale(home: Path) -> None:
    _plant(home, str(_launchd_log(home)), started_at="Fri Oct 16 10:00:00 2026")
    recycled = breadcrumb.read_breadcrumb(home / "state", lstarts=lambda pids: {p: "Sat Oct 17 09:00:00 2026" for p in pids})
    gone = breadcrumb.read_breadcrumb(home / "state", lstarts=lambda pids: {})
    unknown = breadcrumb.read_breadcrumb(home / "state", lstarts=lambda pids: None)
    assert (recycled.status, gone.status, unknown.status) == (breadcrumb.STALE, breadcrumb.STALE, breadcrumb.UNVERIFIED)
