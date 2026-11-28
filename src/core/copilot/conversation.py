
from __future__ import annotations

import os
import re
from typing import Mapping, Optional

from src.core.attention.output_holders import open_vnode_paths
from src.core.attention.parent_map import descendants

_PROGRAM = "copilot"
_HOLD = r"/session-state/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/inuse\.%d\.hold$"


def conversation_of_pid(pid: int) -> Optional[str]:
    held = open_vnode_paths(pid)
    if not held:
        return None
    pattern = re.compile(_HOLD % int(pid))
    for _, path in held:
        found = pattern.search(path)
        if found:
            return found.group(1)
    return None


def conversation_for_pane(pane_pid: Optional[int], parents: Mapping[int, int], commands: Mapping[int, str]) -> Optional[str]:
    if pane_pid is None:
        return None
    root = int(pane_pid)
    for pid in (root, *descendants(root, parents)):
        words = (commands.get(pid) or "").split(None, 1)
        if words and os.path.basename(words[0]) == _PROGRAM:
            found = conversation_of_pid(pid)
            if found:
                return found
    return None
