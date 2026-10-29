
import pytest


@pytest.fixture(autouse=True)
def plain_sessions_record_no_swarm_row(monkeypatch):
    from src.core.swarm import delivery

    async def plain(request, session_id, source_ref):
        return None

    monkeypatch.setattr(delivery, "record_for_paste", plain)


@pytest.fixture(autouse=True)
def forget_held_rows():
    from src.cplugs.huddle import changes_view

    changes_view._SENT.clear()


@pytest.fixture(autouse=True)
def no_personal_addon_skills(monkeypatch):
    from src.cplugs.huddle import mcp

    monkeypatch.setattr(mcp, "stale_extensions", lambda *args, **kwargs: [])


@pytest.fixture(autouse=True)
def no_stored_session_rows(monkeypatch):
    from src.cplugs.host import session_rows

    monkeypatch.setattr(session_rows, "read", lambda keys: {})


@pytest.fixture(autouse=True)
def no_nested_projects(monkeypatch):
    from src.cplugs.host import capabilities

    monkeypatch.setattr(capabilities.Projects, "enclosing", lambda self: {})


@pytest.fixture
def default_structlog():
    import structlog

    saved = structlog.get_config()
    structlog.reset_defaults()
    try:
        yield
    finally:
        structlog.configure(**saved)
