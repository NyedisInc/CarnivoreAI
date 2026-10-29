
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOST_READS = re.compile(r"launchctl|tmutil|brctl|fileproviderd|LaunchAgents|LaunchDaemons")


def _alert_sources() -> list:
    files = [*(ROOT / "src/core/app_alerts").glob("*.py"),
             *(ROOT / "src/core/pipeline").glob("*.py"), *(ROOT / "src/core/self_check").glob("*.py")]
    assert files
    return files


def test_host_health_code_is_gone() -> None:
    assert importlib.util.find_spec("src.core.host_health") is None
    assert importlib.util.find_spec("src.api.host_health_routes") is None
    assert not (ROOT / "scripts/host_health").exists()


ALLOWED_HOST_TOOLS = {
    "src/core/pipeline/reader.py": "brctl",
}


def _host_reads(path: Path, text: str = "") -> list:
    allowed = ALLOWED_HOST_TOOLS.get(path.relative_to(ROOT).as_posix())
    return [m.group(0) for m in HOST_READS.finditer(text or path.read_text()) if m.group(0) != allowed]


def test_no_alert_source_reads_the_host() -> None:
    hits = [p.name for p in _alert_sources() if _host_reads(p)]
    assert hits == []


def test_the_brctl_allowance_is_download_only() -> None:
    for rel in ALLOWED_HOST_TOOLS:
        text = (ROOT / rel).read_text()
        assert not re.search(r"[\"']\s*(evict|status|monitor|dump|log)\s*[\"']", text), rel
    assert "\"download\"" in (ROOT / "src/core/pipeline/reader.py").read_text()


def test_the_allowance_does_not_hide_another_host_read() -> None:
    icloud = ROOT / "src/core/pipeline/reader.py"
    assert _host_reads(icloud, icloud.read_text() + "\nlaunchctl\n") == ["launchctl"]
    assert _host_reads(ROOT / "src/core/pipeline/engine.py", "brctl download x") == ["brctl"]


def test_no_host_health_wiring_route_tool_or_strings() -> None:
    boot_steps = tuple(str(p.relative_to(ROOT)) for p in sorted((ROOT / "src/core/boot").glob("*.py")))
    assert boot_steps, "the boot step package moved; point this check at the lifespan's new home"
    for rel in ("src/main.py", *boot_steps, "src/api/routes.py", "src/core/mcp/read_tools.py", "client/js/i18n/catalog.en.js"):
        text = (ROOT / rel).read_text()
        assert "host_health" not in text and "host-health" not in text, rel


def _tmutil_files(files: list, texts: dict) -> list:
    plugin = "src/cplugs/timemachine/"
    return [rel for p in files if not (rel := p.relative_to(ROOT).as_posix()).startswith(plugin)
            and re.search("tmutil", texts.get(p) or p.read_text(), re.I)]


def test_only_the_timemachine_plugin_reads_tmutil() -> None:
    files = list((ROOT / "src").rglob("*.py"))
    assert len(files) > 100
    assert _tmutil_files(files, {}) == []
    synthetic = ROOT / "src/core/x.py"
    assert _tmutil_files([synthetic], {synthetic: "TmutilRunner = None"}) == ["src/core/x.py"]
