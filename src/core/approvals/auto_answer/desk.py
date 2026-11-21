
from __future__ import annotations

import os
import re
from typing import Any, Optional

from src.core.session_startup_gate import SCREEN_TRUST
from src.core.swarm import launch

ADD_YES_LABEL: str = "Yes, add it"
ADD_LABELS = frozenset({"No, exit", ADD_YES_LABEL})
_HEAD = "Addinganewdirectory:"
_TAIL = ("Thissessionhasn'tworkedherebefore.Isthisadirectoryyoucreatedoroneyoutrust?Claude" "Code'llbeabletoread,edit,andexecutefileshere."
         "Itsskills,commands,andagentsloadandcanruncommands,andsocanthegitsettingsofitsrepository.Youranswerholdsforthissession."
         "StartingClaudeCodeinthisdirectoryandtrustingittherelasts,andcoversitswholerepositoryoreverythingbelowit."
         "SecurityguideNo,exitYes,addit")


def _compact(dialog: Any) -> str:
    kept = [re.sub(r"^[❯›>]\s*", "", ln.strip()) for ln in str(dialog.body).splitlines()]
    return "".join(re.sub(r"\s+", "", ln) for ln in kept if ln and not set(ln) <= {"─", "-", "━"})


def is_add_directory_dialog(dialog: Any) -> bool:
    return (dialog is not None and getattr(dialog, "family", None) == "claude" and getattr(dialog, "startup_kind", None) == SCREEN_TRUST
            and len(dialog.rows) == len(ADD_LABELS) and {str(r.label).strip() for r in dialog.rows} == ADD_LABELS)


def shown_folder(dialog: Any) -> Optional[str]:
    text = _compact(dialog)
    if not text.startswith(_HEAD) or not text.endswith(_TAIL):
        return None
    shown = text[len(_HEAD):len(text) - len(_TAIL)]
    return shown if shown.startswith("/") and "…" not in shown else None


def owned_desk_folder(shown: str) -> Optional[str]:
    from src.config import settings

    state = settings.get_state_dir()
    base = launch.desk_dir(state, 0).parent
    for root in {str(base), os.path.realpath(base)}:
        prefix = re.sub(r"\s+", "", root) + os.sep
        if shown.startswith(prefix) and re.fullmatch(r"[0-9]{1,9}", shown[len(prefix):]):
            folder = os.path.join(os.path.realpath(base), shown[len(prefix):])
            if os.path.isdir(folder) and not os.path.islink(folder) and os.path.realpath(folder) == folder:
                return folder
    return None
