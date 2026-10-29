
import hashlib
import json
import re
import shutil
import subprocess
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
LOCK = ROOT / "requirements.lock"
MAC = ROOT / "macOS"
node = shutil.which("node")
needs_node = pytest.mark.skipif(node is None, reason="node is not installed")


def _checker():
    sys.path.insert(0, str(ROOT / "scripts" / "release"))
    try:
        import requirements_lock
    finally:
        sys.path.pop(0)
    return requirements_lock


def _node(script: str, *args: str) -> str:
    done = subprocess.run([node, "-e", textwrap.dedent(script), *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()



def test_the_committed_lock_passes_the_checker():
    lock = _checker()
    problems = lock.check_lock(LOCK.read_text(), (ROOT / "requirements.txt").read_text())
    assert problems == []
    assert len(lock.parse_lock(LOCK.read_text())) >= 40, "the lock looks empty or truncated"


def test_the_checker_rejects_a_bad_hash_an_unpinned_line_or_a_url():
    lock = _checker()
    text, reqs = LOCK.read_text(), (ROOT / "requirements.txt").read_text()
    first = re.search(r"--hash=sha256:([0-9a-f]{64})", text).group(1)
    assert lock.check_lock(text.replace(first, first[:-1], 1), reqs), "a 63 digit hash must be rejected"
    name = re.search(r"^([A-Za-z0-9_.\-]+)==", text, re.M).group(1)
    entry = re.search(rf"^{re.escape(name)}==[^\n]*(?:\n[ \t]+[^\n]*)*", text, re.M).group(0)
    bare = text.replace(entry, f"{name}==0.0.1\n", 1)
    assert any("hash" in p for p in lock.check_lock(bare, reqs)), "an entry with no hash must be rejected"
    h = "    --hash=sha256:" + "a" * 64 + "\n"
    ok = "foo==1.0 \\\n" + h
    assert lock.check_lock(ok, "foo\n") == []
    for bad in ("foo>=1.0 \\\n" + h, "foo @ https://example.com/foo.whl \\\n" + h,
                "--extra-index-url https://example.com/simple\n" + ok,
                ok + "    # https://x/releases/latest/download/foo\n"):
        assert lock.check_lock(bad, "foo\n"), bad
    assert lock.check_lock(ok, "foo\nbar\n"), "bar is in requirements.txt and missing from the lock"
    assert lock.check_lock(ok, "foo>=2\n"), "1.0 does not satisfy foo>=2"



def _tiny_wheel(directory: Path) -> Path:
    wheel = directory / "tinypkg-1.0-py3-none-any.whl"
    files = {
        "tinypkg/__init__.py": "VALUE = 1\n",
        "tinypkg-1.0.dist-info/METADATA": "Metadata-Version: 2.1\nName: tinypkg\nVersion: 1.0\n",
        "tinypkg-1.0.dist-info/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        "tinypkg-1.0.dist-info/RECORD": "",
    }
    with zipfile.ZipFile(wheel, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return wheel


def _pip_install(args: list, lock: Path, wheels: Path, target: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pip", "install", "--no-index", "--find-links", str(wheels),
                           "--target", str(target), *args, "-r", str(lock)],
                          capture_output=True, text=True, timeout=120)


@needs_node
def test_pip_refuses_a_changed_hash_with_the_flags_bootstrap_passes(tmp_path):
    wheel = _tiny_wheel(tmp_path)
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    flags = json.loads(_node("""
        const { buildPipInstallArgs } = require('./macOS/python-lock.js');
        console.log(JSON.stringify(buildPipInstallArgs('LOCKPATH')));
        """))
    assert flags[-2:] == ["-r", "LOCKPATH"] and "--require-hashes" in flags and "--no-deps" in flags
    assert flags[flags.index("--only-binary") + 1] == ":all:"
    enforced = [f for f in flags[:-2] if f not in ("install", "--disable-pip-version-check")]
    good, bad = tmp_path / "good.lock", tmp_path / "bad.lock"
    good.write_text(f"tinypkg==1.0 \\\n    --hash=sha256:{digest}\n")
    flipped = digest[:-1] + ("0" if digest[-1] != "0" else "1")
    bad.write_text(f"tinypkg==1.0 \\\n    --hash=sha256:{flipped}\n")
    ok = _pip_install(enforced, good, tmp_path, tmp_path / "t-good")
    assert ok.returncode == 0, ok.stderr
    assert (tmp_path / "t-good" / "tinypkg" / "__init__.py").exists()
    refused = _pip_install(enforced, bad, tmp_path, tmp_path / "t-bad")
    assert refused.returncode != 0 and "HASH" in refused.stderr.upper()
    assert not (tmp_path / "t-bad" / "tinypkg").exists()



def test_bootstrap_installs_only_from_the_lock():
    text = (MAC / "bootstrap.js").read_text()
    assert "'-r', requirementsPath" not in text, "an unhashed pip call is left in bootstrap.js"
    assert "buildPipInstallArgs(lockPath)" in text
    assert "sha256File(lockPath)" in text and "sha256File(requirementsPath)" not in text, \
        ".deps-hash must key on the lock"
    assert "python-too-new" in text


def test_the_lock_is_shipped_resynced_and_deployed():
    pkg = json.loads((MAC / "package.json").read_text())
    entries = {(e.get("from"), e.get("to")) for e in pkg["build"]["extraResources"] if isinstance(e, dict)}
    assert ("../requirements.lock", "requirements.lock") in entries
    block = re.search(r"const RESYNC_ALLOWLIST\s*=\s*\[(.*?)\];", (MAC / "bootstrap.js").read_text(), re.DOTALL).group(1)
    assert "name: 'requirements.lock', isDir: false" in block
    ship = re.search(r"^SHIP_PATHS=\((.*?)\)", (ROOT / "scripts" / "deploy-mini.sh").read_text(), re.M).group(1)
    assert "requirements.lock" in ship.split()


def test_the_release_script_records_a_pip_audit():
    text = (MAC / "scripts" / "release-build.sh").read_text()
    assert "pip-audit-lock.sh" in text
    script = (MAC / "scripts" / "pip-audit-lock.sh").read_text()
    assert "not run" in script and "requirements.lock" in script



def test_no_latest_url_remains():
    for name in ("server-manager.js", "cloudflared-pin.js"):
        assert "releases/latest" not in (MAC / name).read_text(), name
    pin = (MAC / "cloudflared-pin.js").read_text()
    assert len(re.findall(r"'[0-9a-f]{64}'", pin)) >= 4, "both arches need an archive and a binary sha256"
    assert "/releases/download/" in pin


_CF = """
    const fs = require('fs'), os = require('os'), path = require('path'), crypto = require('crypto');
    const cf = require('./macOS/cloudflared-pin.js');
    const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
    const mode = process.argv[1];
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cfpin-'));
    const archive = Buffer.from(mode === 'bad-archive' ? 'tampered archive' : 'good archive');
    const binary = Buffer.from(mode === 'bad-binary' ? 'tampered binary' : 'good binary');
    const pins = { arm64: { url: 'https://example.invalid/cloudflared-darwin-arm64.tgz',
                            archiveSha256: sha(Buffer.from('good archive')), binarySha256: sha(Buffer.from('good binary')) } };
    let extracted = false;
    const download = async (url, dest) => { if (!url.includes('/cloudflared-darwin-arm64.tgz')) throw new Error('bad url'); fs.writeFileSync(dest, archive); };
    const extract = async (tgz, outDir) => { extracted = true; fs.writeFileSync(path.join(outDir, 'cloudflared'), binary); };
    if (mode === 'stale-file') { fs.writeFileSync(path.join(dir, 'cloudflared'), 'old unhashed binary', { mode: 0o755 }); }
    (async () => {
      let error = null, result = null;
      try { result = await cf.ensureVerified({ binDir: dir, arch: 'arm64', pins, download, extract }); }
      catch (e) { error = String(e.message || e); }
      const bin = path.join(dir, 'cloudflared');
      console.log(JSON.stringify({ error, extracted, result, exists: fs.existsSync(bin),
        mode: fs.existsSync(bin) ? (fs.statSync(bin).mode & 0o777).toString(8) : null,
        left: fs.readdirSync(dir) }));
    })();
"""


@needs_node
def test_cloudflared_is_verified_before_it_is_made_executable():
    good = json.loads(_node(_CF, "good"))
    assert good["error"] is None and good["exists"] and good["mode"] == "755" and good["left"] == ["cloudflared"]
    stale = json.loads(_node(_CF, "stale-file"))
    assert stale["error"] is None and stale["extracted"] and stale["mode"] == "755", "an unhashed old binary is replaced"
    for mode in ("bad-archive", "bad-binary"):
        bad = json.loads(_node(_CF, mode))
        assert bad["error"] and "sha256" in bad["error"], mode
        assert not bad["exists"] and bad["left"] == [], f"{mode}: nothing may stay on disk"
    assert json.loads(_node(_CF, "bad-archive"))["extracted"] is False, "a bad archive is refused before extraction"



@needs_node
def test_python_range_is_312_to_314_and_a_newer_minor_is_named():
    out = json.loads(_node("""
        const { classifyPython, tooNewMessage } = require('./macOS/python-lock.js');
        const v = ['Python 3.11.9', 'Python 3.12.0', 'Python 3.13.5', 'Python 3.14.7', 'Python 3.15.0', 'Python 4.0.1', 'junk'];
        console.log(JSON.stringify({ verdicts: v.map((s) => classifyPython(s).verdict), message: tooNewMessage('3.15.0') }));
        """))
    assert out["verdicts"] == ["too-old", "ok", "ok", "ok", "too-new", "too-new", "unparsable"]
    assert "3.15.0" in out["message"] and "3.12" in out["message"] and "3.14" in out["message"]


@needs_node
def test_a_venv_outside_the_proven_range_is_rebuilt_not_reused():
    out = json.loads(_node("""
        const { venvNeedsRebuild } = require('./macOS/python-lock');
        console.log(JSON.stringify({
          ok: venvNeedsRebuild(0, 'Python 3.13.1'),
          new: venvNeedsRebuild(0, 'Python 3.15.0'),
          old: venvNeedsRebuild(0, 'Python 3.11.9'),
          broken: venvNeedsRebuild(1, ''),
          garbled: venvNeedsRebuild(0, 'nope'),
        }));
    """))
    assert out == {"ok": False, "new": True, "old": True, "broken": True, "garbled": True}
    text = (MAC / "bootstrap.js").read_text()
    assert "venvNeedsRebuild(probe.code" in text, "bootstrap no longer probes the reused venv"
