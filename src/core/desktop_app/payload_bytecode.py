"""Interpreter flags that keep the bundled python from writing bytecode into the signed app (#2490).

The Mac shell exports PYTHONPYCACHEPREFIX (or PYTHONDONTWRITEBYTECODE) to the engine on the payload python. A launch that
runs ``python -I`` ignores those variables, and a pane or a user's terminal never inherits them, so such a launch carries the
same choice as command-line flags instead.
"""
from __future__ import annotations

import os
from typing import List, Mapping, Optional


def bytecode_flags(env: Optional[Mapping[str, str]] = None) -> List[str]:
    """The python flags matching the bytecode variables in ``env`` (default: this process's environment).

    Input: env - mapping to read. Output: ``["-X", "pycache_prefix=<dir>"]`` when PYTHONPYCACHEPREFIX is set, else ``["-B"]``
    when PYTHONDONTWRITEBYTECODE is set, else ``[]`` (a development checkout is left alone).
    Example: ``bytecode_flags({"PYTHONPYCACHEPREFIX": "/c"}) == ["-X", "pycache_prefix=/c"]``.
    """
    source = os.environ if env is None else env
    prefix = source.get("PYTHONPYCACHEPREFIX")
    if prefix:
        return ["-X", f"pycache_prefix={prefix}"]
    if source.get("PYTHONDONTWRITEBYTECODE"):
        return ["-B"]
    return []
