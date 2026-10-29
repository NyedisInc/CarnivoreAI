
from __future__ import annotations

import json

from src.core import slash_favorites



def _config_file(tmp_path, entries):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"common_slash_commands": entries}, indent=2))
    return path


def test_an_entry_with_no_description_is_written_as_a_bare_string(tmp_path):
    path = _config_file(tmp_path, [])
    slash_favorites.write(
        path,
        [
            "/clear",
            {"command": "/empty", "description": ""},
            {"command": "/blank", "description": "   "},
            {"command": "/absent"},
            {"command": "/null", "description": None},
        ],
    )
    stored = json.loads(path.read_text())["common_slash_commands"]
    assert stored == ["/clear", "/empty", "/blank", "/absent", "/null"]


def test_a_real_description_keeps_the_object_form(tmp_path):
    path = _config_file(tmp_path, [])
    slash_favorites.write(
        path,
        [{"command": "/diff", "description": "review changes"}, "/clear"],
    )
    stored = json.loads(path.read_text())["common_slash_commands"]
    assert stored == [
        {"command": "/diff", "description": "review changes"},
        "/clear",
    ]


def test_normalizing_the_write_does_not_change_what_is_rendered(tmp_path):
    path = _config_file(tmp_path, [])
    slash_favorites.write(path, [{"command": "/diff", "description": ""}])
    details = slash_favorites.payload(path)["command_details"]
    assert details == [{"command": "/diff", "description": "review changes", "color": None}]
