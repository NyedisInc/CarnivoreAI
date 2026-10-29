
import shutil
import subprocess
from pathlib import Path

import pytest

API_JS = Path(__file__).resolve().parents[3] / "client" / "js" / "api.js"

_SCRIPT = r"""
const fs = require('fs');
global.window = { location: { protocol: 'http:', host: 'x' } };
global.localStorage = { getItem: () => 'tok', setItem() {}, removeItem() {} };
global.document = { addEventListener() {} };
global.fetch = async () => ({ ok: false, status: 503, json: async () => (
  { detail: { code: 'peer_unavailable', detail: 'hosta is not connected' } }) });
(0, eval)(fs.readFileSync(process.argv[1], 'utf8') + '\nglobal.API = window.API;');
API.destroySession('remote:peer-x').then(() => console.log('NOERR'),
  (e) => console.log('MSG=' + e.message));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_peer_refusal_sentence_reaches_the_alert() -> None:
    out = subprocess.run(["node", "-e", _SCRIPT, str(API_JS)], capture_output=True, text=True, timeout=30)
    assert "MSG=hosta is not connected" in out.stdout, out.stdout + out.stderr


_UPLOAD_SCRIPT = _SCRIPT.replace("hosta is not connected", "hosta runs an older carnivore without this action").replace(
    "API.destroySession('remote:peer-x')", "API.uploadFile({ type: 'text/plain' }, 'a.txt', 'remote:peer-x')").replace(
    "global.document =", "global.FormData = class { append() {} };\nglobal.document =")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_upload_refusal_sentence_is_not_object_object() -> None:
    out = subprocess.run(["node", "-e", _UPLOAD_SCRIPT, str(API_JS)], capture_output=True, text=True, timeout=30)
    assert "MSG=hosta runs an older carnivore without this action" in out.stdout, out.stdout + out.stderr
