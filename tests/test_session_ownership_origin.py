
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.core.tmux_backend import TmuxBackend

SESSION_MANAGER_PATH = ROOT / "src" / "core" / "session_manager.py"
LEDGER_PATH = ROOT / "src" / "core" / "sessions" / "owned_tmux_ledger.py"
ATTACHABLE_PARSER_PATH = ROOT / "src" / "core" / "sessions" / "tmux_listing_fold.py"


class _FakeProbeBackend:

    def __init__(self, rows):
        self._rows = rows

    def _run_listing(self, *_args):
        text = "\n".join(
            f"${index}|{epoch}|1|{name}"
            for index, (name, epoch) in enumerate(self._rows)
        )
        return None, text

    list_attachable_sessions = TmuxBackend.list_attachable_sessions


def _badges(rows, **kwargs):
    listing = _FakeProbeBackend(rows).list_attachable_sessions(**kwargs)
    assert listing.ok
    return {row["name"]: row["created_by_cloude"] for row in listing.sessions}




def test_ownership_resolves_on_the_INSTANCE_not_the_name():
    badges = _badges(
        [("foo", 2000), ("bar", 3000)],
        owned_instances={("foo", 1000)},
    )
    assert badges["foo"] is False, (
        "the reused name inherited the dead instance's ownership badge"
    )
    assert badges["bar"] is False


def test_the_matching_instance_does_badge_as_ours():
    badges = _badges([("foo", 1000)], owned_instances={("foo", 1000)})
    assert badges["foo"] is True


def test_a_None_epoch_is_NOT_a_wildcard_and_never_badges_a_stranger():
    badges = _badges([("foo", 9999)], owned_instances={("foo", None)})
    assert badges["foo"] is False


def test_a_stored_epoch_for_a_name_OVERRIDES_the_legacy_name_tier():
    badges = _badges(
        [("foo", 9999)],
        owned_instances={("foo", 1000)},
        owned_names={"foo"},
    )
    assert badges["foo"] is False


def test_the_legacy_name_tier_applies_when_the_DB_is_SILENT_on_that_name():
    badges = _badges(
        [("fresh", 9999)],
        owned_instances={("other", 1000)},
        owned_names={"fresh"},
    )
    assert badges["fresh"] is True


def test_owned_instances_takes_precedence_over_owned_names():
    badges = _badges(
        [("foo", 2000)],
        owned_names={"foo"},
        owned_instances={("foo", 1000)},
    )
    assert badges["foo"] is False


def test_the_name_tier_still_works_when_no_instances_are_supplied():
    badges = _badges([("foo", 2000), ("bar", 1)], owned_names={"foo"})
    assert badges == {"foo": True, "bar": False}


def test_an_empty_instance_set_means_nothing_is_owned_not_fall_back():
    badges = _badges([("cloude_x", 1)], owned_instances=set())
    assert badges["cloude_x"] is False


def test_with_neither_source_the_prefix_heuristic_still_applies():
    badges = _badges([("cloude_x", 1), ("other", 2)])
    assert badges == {"cloude_x": True, "other": False}




def test_the_ownership_decision_lives_in_ONE_place_in_session_manager():
    source = SESSION_MANAGER_PATH.read_text()
    tree = ast.parse(source)

    allowed = {
        "rename_session",
        "destroy_external_session",
    }

    offenders = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if func.name in allowed:
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Compare):
                continue
            if not any(isinstance(op, ast.In) for op in node.ops):
                continue
            for comparator in node.comparators:
                if getattr(comparator, "attr", None) != "names":
                    continue
                if getattr(getattr(comparator, "value", None), "attr", None) == "_owned":
                    offenders.append((func.name, node.lineno))

    assert offenders == [], (
        "these functions test membership of the owned name set directly "
        f"instead of going through the shared resolver: {offenders}. That "
        "is exactly how the badge came to disagree with itself before"
    )


def test_owned_tmux_sessions_is_still_alive_this_commit():
    source = LEDGER_PATH.read_text()
    assert "self.names: set[str] = set()" in source
    assert 'payload["owned_tmux_sessions"] = sorted(self.names)' in source


def test_the_adopt_path_now_persists_origin():
    from contextlib import closing

    from src.core.db_models import SESSION_ORIGIN_ADOPTED
    from src.core.session_adopt_persist import persist_adoption
    from src.core.session_manager import SessionManager
    from tests.s7_helpers import (
        TEST_SOCKET,
        listing_of,
        listing_row,
        migrated_connection,
        session_row,
    )

    assert hasattr(SessionManager, "persist_adoption"), (
        "SessionManager.persist_adoption is the S7 wire between "
        "POST /sessions/adopt and sessions.origin. Without it an "
        "adoption is recorded nowhere and does not survive a restart"
    )
    import tempfile

    with tempfile.TemporaryDirectory() as state_dir:
        with closing(migrated_connection(Path(state_dir))) as conn:
            listing = listing_of([listing_row("ext", 4242)])
            result = persist_adoption(
                conn, socket=TEST_SOCKET, name="ext", listing=listing
            )
            assert result.persisted, result.detail
            stored = session_row(conn, "ext")
            assert stored["origin"] == SESSION_ORIGIN_ADOPTED
            assert stored["adopted_at"] is not None


def test_the_backend_resolution_order_is_documented_in_code():
    source = (ROOT / "src" / "core" / "tmux_listing_parse.py").read_text()
    assert "if (name, created_at_epoch) in owned_instances:" in source
    assert "return name in owned_names" in source
    assert "return bool(prefix) and is_owned_session_name(name)" in source
    assert "owned_name == name and owned_epoch is not None" in source
    parser = ATTACHABLE_PARSER_PATH.read_text()
    assert "created_by_cloude = resolve_ownership(" in parser
    assert "def resolve_ownership" not in parser


def test_no_em_or_en_dashes_in_the_files_this_step_authored():
    authored = [
        ROOT / "src" / "core" / "session_store.py",
        ROOT / "src" / "core" / "session_import.py",
        Path(__file__),
        ROOT / "tests" / "test_session_store.py",
        ROOT / "tests" / "test_session_import.py",
        ROOT / "src" / "core" / "tmux_listing.py",
        ROOT / "src" / "core" / "tmux_listing_parse.py",
        ROOT / "src" / "core" / "session_identity.py",
        ROOT / "tests" / "test_s4_adversarial.py",
        ROOT / "tests" / "test_tmux_listing_parse.py",
        ROOT / "tests" / "test_s4_regressions.py",
    ]
    for path in authored:
        text = path.read_text(encoding="utf-8")
        assert text.count(chr(8212)) == 0, f"em-dash in {path.name}"
        assert text.count(chr(8211)) == 0, f"en-dash in {path.name}"
