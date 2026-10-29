import os
from unittest import mock

from src.core.sessions import agent_update


def _touch(path, mtime_ns):
    path.write_text("")
    os.utime(path.parent, ns=(mtime_ns, mtime_ns))


def test_repeated_calls_list_once_and_new_version_is_picked_up(tmp_path):
    agent_update._NEWEST_VERSION_CACHE.clear()
    versions = tmp_path / "versions"
    versions.mkdir()
    _touch(versions / "2.1.301", 1_000_000_000)
    real_listdir = os.listdir
    with mock.patch.object(agent_update.os, "listdir", side_effect=real_listdir) as spy:
        results = [agent_update._newest_version_in(str(versions)) for _ in range(50)]
        assert results == ["2.1.301"] * 50
        assert spy.call_count == 1
        _touch(versions / "2.1.302", 2_000_000_000)
        assert agent_update._newest_version_in(str(versions)) == "2.1.302"
        assert spy.call_count == 2
