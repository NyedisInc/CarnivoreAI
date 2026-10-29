
from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.core import theme_script_consent as consent

_REPO = Path(__file__).resolve().parents[3]
_MODULE = _REPO / "client" / "js" / "theme-consent.js"
_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64

_NODE_DRIVER = """
const api = require(process.argv[1]);
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = {
  decide: cases.decide.map((c) => api.decide({
    declaresScript: c.declares_script, source: c.source, servedDigest: c.served_digest,
    record: c.record, recordReadable: c.record_readable, scriptTrust: c.script_trust })),
  record_for: cases.record_for.map((c) => api.recordFor(c[0], c[1])),
  revocations: cases.revocations.map((c) => api.revocationsBetween(c[0], c[1])),
};
process.stdout.write('\\n' + JSON.stringify(out));
"""


def _node_available() -> bool:
    try:
        return subprocess.run(["node", "--version"], capture_output=True, check=False).returncode == 0
    except OSError:
        return False


def _decide_cases() -> List[Dict[str, Any]]:
    records = [None, {"decision": "never"}, {"decision": "always", "digest": _DIGEST_A},
               {"decision": "always", "digest": _DIGEST_B}, {"decision": "always"}]
    grid = itertools.product(
        [True, False], ["builtin", "user", "other"], [None, _DIGEST_A, "not-a-digest"], records,
        [True, False], [None, "first_party"])
    return [dict(zip(("declares_script", "source", "served_digest", "record", "record_readable", "script_trust"), row))
            for row in grid]


@pytest.mark.skipif(not _node_available(), reason="node is not available in this environment")
def test_the_python_ladder_answers_what_the_client_gate_answers() -> None:
    record_for = [(d, g) for d in ("always", "never", "once", "x") for g in (None, _DIGEST_A, "bad")]
    revocations = [({}, {"m": {"decision": "never"}}), ({"m": {"decision": "never"}}, {"m": {"decision": "never"}}),
                   ({"m": {"decision": "always", "digest": _DIGEST_A}}, {"m": {"decision": "never"}}),
                   (None, None), ({"a": {"decision": "never"}}, {})]
    cases = {"decide": _decide_cases(), "record_for": record_for, "revocations": revocations}
    done = subprocess.run(["node", "-e", _NODE_DRIVER, str(_MODULE)], input=json.dumps(cases),
                          capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    client = json.loads(done.stdout.splitlines()[-1])

    assert [len(client[k if k != "revocations" else "revocations"]) for k in cases] == [len(cases[k]) for k in cases]
    for case, got in zip(cases["decide"], client["decide"]):
        want = consent.decide(**case).as_payload()
        assert want == got, f"decide differs for {case}: python {want}, client {got}"
    for (decision, digest), got in zip(record_for, client["record_for"]):
        assert consent.record_for(decision, digest) == got, f"record_for differs for {decision}, {digest}"
    for (before, after), got in zip(revocations, client["revocations"]):
        assert list(consent.revocations_between(before, after)) == got, f"revocations differ for {before}, {after}"
