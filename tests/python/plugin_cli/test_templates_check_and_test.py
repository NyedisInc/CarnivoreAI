
from __future__ import annotations

import json
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List

import pytest

from scripts.plugin import check, plugin, templates


def run(*argv: str) -> int:
    return plugin.main(list(argv))


def scaffold(tmp_path: Path, template: str, name: str = "clock") -> Path:
    assert run("new", name, "--template", template, "--dir", str(tmp_path / name)) == 0
    return tmp_path / name


def edit_manifest(folder: Path, mutate) -> None:
    path = folder / "carnivore.toml"
    path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")


@pytest.mark.parametrize("template", templates.TEMPLATES)
def test_each_template_passes_check_and_test(tmp_path: Path, template: str, capsys: pytest.CaptureFixture) -> None:
    folder = scaffold(tmp_path, template)
    assert run("check", str(folder)) == 0, capsys.readouterr().out
    assert run("test", str(folder)) == 0, capsys.readouterr().out[-1500:]
    assert "plugin test: ok" in capsys.readouterr().out


def test_a_setting_named_like_a_credential_warns_and_points_at_the_keychain(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    folder = scaffold(tmp_path, "sidecar")
    edit_manifest(
        folder,
        lambda t: t.replace(
            'inputSchema = { type = "object", properties = {}, additionalProperties = false }',
            'inputSchema = { type = "object", properties = { apiToken = { type = "string" } }, additionalProperties = false }',
        ),
    )
    report = check.check_folder(folder)
    assert report.ok and any("apiToken" in w and "Keychain" in w for w in report.warnings), report
    assert run("check", str(folder)) == 0 and "warning:" in capsys.readouterr().out


@pytest.mark.parametrize("mutate", [
    lambda t: t.replace('version = "0.1.0"\n', ""),
    lambda t: t.replace('id = "clock"', 'id = "Bad-Id"'),
    lambda t: t.replace('clock_main.py', 'missing.py'),
    lambda t: t + 'surprise = true\n',
    lambda t: t + '[permissions]\nwrite = ["no.such.permission"]\n',
])
def test_a_broken_manifest_fails_check(tmp_path: Path, mutate) -> None:
    folder = scaffold(tmp_path, "sidecar")
    edit_manifest(folder, mutate)
    assert run("check", str(folder)) == 1


def test_a_tool_the_entry_never_registers_fails_test(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    folder = scaffold(tmp_path, "sidecar")
    (folder / "clock_main.py").write_text(
        'import asyncio\nfrom cplug_sdk import Plugin\n\nplugin = Plugin()\n\nif __name__ == "__main__":\n    asyncio.run(plugin.serve())\n',
        encoding="utf-8",
    )
    assert run("test", str(folder)) == 1
    assert "sandbox smoke failed" in capsys.readouterr().out


def test_a_failing_own_test_fails_the_command(tmp_path: Path) -> None:
    folder = scaffold(tmp_path, "sidecar")
    (folder / "tests" / "test_clock.py").write_text("def test_no():\n    assert False\n", encoding="utf-8")
    assert run("test", str(folder)) == 1


def test_pack_copies_v2_folder_leaves_tests_out_and_keeps_the_page_floor(tmp_path: Path) -> None:
    folder = scaffold(tmp_path, "page")
    out = tmp_path / "dist"
    assert run("pack", str(folder), "--out", str(out), "--publisher", "harbor") == 0
    doc = tomllib.loads((out / "carnivore.toml").read_text(encoding="utf-8"))
    assert doc["id"] == "clock" and doc["min_app_version"] == "1.16.6"
    assert not (out / "cplug.json").exists()
    assert (out / "views" / "face" / "index.html").is_file() and not (out / "tests").exists()
    assert run("pack", str(folder), "--out", str(out)) == 2, "an existing output folder is never overwritten"


def test_new_refuses_a_reserved_name_and_an_existing_folder(tmp_path: Path) -> None:
    assert run("new", "flow", "--dir", str(tmp_path / "a")) == 2
    scaffold(tmp_path, "minimal")
    assert run("new", "clock", "--dir", str(tmp_path / "clock")) == 2


def test_link_posts_the_folder_to_the_sideload_route_with_the_token_from_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: List[Dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status": "consent_needed"}')

        def log_message(self, *args: Any) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    folder = scaffold(tmp_path, "minimal")
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        monkeypatch.delenv(plugin.TOKEN_ENV, raising=False)
        assert run("link", str(folder), "--base", base) == 2 and seen == []
        monkeypatch.setenv(plugin.TOKEN_ENV, "tok")
        assert run("link", str(folder), "--base", base) == 0
    finally:
        server.shutdown()
    assert seen == [{"path": plugin.SIDELOAD_PATH, "auth": "Bearer tok", "body": {"path": str(folder.resolve())}}]
