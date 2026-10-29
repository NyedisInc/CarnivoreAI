import subprocess
import sys

import pytest

from src.core.iopolicy import materialize as iop

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="I/O policy for dataless files is macOS only")

_PROBE = (
    "import ctypes,ctypes.util,subprocess,sys;"
    "l=ctypes.CDLL(ctypes.util.find_library('c'));"
    "child=subprocess.run([sys.executable,'-c',"
    "\"import ctypes,ctypes.util;l=ctypes.CDLL(ctypes.util.find_library('c'));print(l.getiopolicy_np(3,0))\"],"
    "capture_output=True,text=True).stdout.strip();"
    "print(l.getiopolicy_np(3,0),child)"
)


def _probe(preexec):
    out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, preexec_fn=preexec, check=True)
    return out.stdout.split()


def test_child_and_grandchild_get_materialization_on_parent_unchanged():
    before = iop.current_policy()
    assert _probe(iop.spawn_preexec()) == [str(iop.IOPOL_MATERIALIZE_DATALESS_FILES_ON)] * 2
    assert iop.current_policy() == before


def test_probe_can_read_off():
    force_off = lambda: iop._LIBC.setiopolicy_np(3, 0, 1)  # noqa: E731
    assert _probe(force_off) == ["1", "1"]
