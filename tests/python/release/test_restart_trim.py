
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "scripts" / "deploy-dmg.sh"

_NODE = textwrap.dedent(
    """
    const fs = require('fs'), os = require('os'), path = require('path');
    const b = require(path.join(process.argv[1], 'macOS', 'bootstrap.js'));
    if (process.argv[2] === 'nokeep') for (const i of b.RESYNC_ALLOWLIST) delete i.keep;
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trim-'));
    const res = path.join(root, 'Resources'), srv = path.join(root, 'server');
    const put = (base, rel, text) => {
      const f = path.join(base, rel); fs.mkdirSync(path.dirname(f), { recursive: true });
      fs.writeFileSync(f, text);
    };
    put(res, 'src/main.py', 'print(1)'); put(res, 'src/core/a.py', 'a = 1');
    put(res, 'client/index.html', '<html>'); put(res, 'features/index.json', '{}');
    const sync = () => b.syncBundledAssets({ serverDir: srv, bundleResourcesDir: res, isPackaged: true });
    const ino = (rel) => fs.statSync(path.join(srv, rel)).ino;
    const files = ['src/main.py', 'src/core/a.py', 'client/index.html', 'features/index.json'];
    if (!sync().ok) throw new Error('first sync failed');
    put(srv, 'src/core/__pycache__/a.cpython-314.pyc', 'compiled');
    const before = Object.fromEntries(files.map((f) => [f, ino(f)]));
    const pycBefore = ino('src/core/__pycache__/a.cpython-314.pyc');
    if (!sync().ok) throw new Error('second sync failed');
    const rewritten = files.filter((f) => ino(f) !== before[f]);
    const pyc = path.join(srv, 'src/core/__pycache__/a.cpython-314.pyc');
    const out = { rewritten, pycSurvived: fs.existsSync(pyc),
                  pycRewritten: fs.existsSync(pyc) && ino('src/core/__pycache__/a.cpython-314.pyc') !== pycBefore };
    put(res, 'src/core/a.py', 'a = 2222');
    if (!sync().ok) throw new Error('third sync failed');
    out.changedRewritten = ino('src/core/a.py') !== before['src/core/a.py'];
    out.changedContent = fs.readFileSync(path.join(srv, 'src/core/a.py'), 'utf8');
    console.log(JSON.stringify(out));
    """
)

node = shutil.which("node")


def _run(mode: str) -> dict:
    proc = subprocess.run([node, "-e", _NODE, str(ROOT), mode], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(node is None or shutil.which("rsync") is None, reason="needs node and rsync")
class TestUnchangedResync:
    def test_second_sync_rewrites_nothing_and_keeps_compiled_modules(self):
        out = _run("keep")
        assert out["rewritten"] == [], f"unchanged files were copied again: {out['rewritten']}"
        assert out["pycSurvived"] and not out["pycRewritten"]

    def test_a_changed_file_is_still_copied(self):
        out = _run("keep")
        assert out["changedRewritten"] and out["changedContent"] == "a = 2222"

    def test_control_without_keep_the_compiled_module_is_deleted(self):
        assert _run("nokeep")["pycSurvived"] is False


class TestDeployStagesBeforeStop:
    @pytest.fixture(scope="class")
    def lines(self):
        return DEPLOY.read_text().splitlines()

    @staticmethod
    def _first(lines, pattern):
        rx = re.compile(pattern)
        return next(i for i, line in enumerate(lines) if rx.search(line) and not line.lstrip().startswith("#"))

    def test_ditto_and_signature_check_precede_the_stop(self, lines):
        stop = self._first(lines, r'^boot_out_all_carnivore_jobs$')
        assert self._first(lines, r'^ditto .* "\$STAGED_APP"') < stop
        assert self._first(lines, r'^codesign --verify --deep --strict "\$STAGED_APP"') < stop
        assert self._first(lines, r'^if ! codesign --verify -R="\$PIN_REQ" "\$STAGED_APP"') < stop

    def test_no_ditto_inside_the_downtime_window(self, lines):
        stop = self._first(lines, r'^boot_out_all_carnivore_jobs$')
        assert not [l for l in lines[stop:] if re.match(r"^ditto\b", l)]

    def test_contents_swap_follows_the_port_free_wait(self, lines):
        wait = self._first(lines, r'^wait_for_port_free 8000$')
        swap = self._first(lines, r'^if ! python3 -I "\$SWAP_HELPER" "\$APP/Contents" "\$STAGED_APP/Contents"; then$')
        assert swap > wait
        assert self._first(lines, r'^if ! mv "\$STAGED_APP/Contents" "\$OLD/Contents"; then$') > swap

    def test_swap_is_atomic_and_preflighted_before_the_stop(self, lines):
        stop = self._first(lines, r'^boot_out_all_carnivore_jobs$')
        assert self._first(lines, r'^if ! python3 -I "\$SWAP_HELPER" --check ') < stop
        code = [l for l in lines if not l.lstrip().startswith("#")]
        assert not [l for l in code if re.search(r'mv "\$APP/Contents"', l)]
        assert not [l for l in code if re.search(r'mv .* "\$APP/Contents"', l)]

    def test_live_app_is_never_renamed_or_moved(self, lines):
        code = [l for l in lines if not l.lstrip().startswith("#")]
        assert not [l for l in code if re.match(r'^\s*mv "\$APP" ', l)]
        assert not [l for l in code if re.search(r'mv .* "\$APP"$', l)]

    def test_polls_are_sub_second(self, lines):
        text = "\n".join(lines)
        assert "POLL_S=0.2" in text and 'sleep "$POLL_S"' in text
