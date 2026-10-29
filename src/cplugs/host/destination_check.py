
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Mapping, Tuple

from src.cplugs.sdk import destination_rules
from src.cplugs.sdk.data_decl import ROLE_BACKUP_DESTINATION, DataDecl
from src.cplugs.sdk.definition import SettingsWarning

SAME_DISK_CODE = "same_disk_app_data"
SAME_DISK_MESSAGE = "same disk as your app data"


def _destination_items(decls: Any, settings: Mapping[str, Any]) -> List[Tuple[str, str]]:
    wanted = {d.root_setting for d in decls or () if isinstance(d, DataDecl) and d.role == ROLE_BACKUP_DESTINATION and d.root_setting}
    return [(k, v.strip()) for k, v in settings.items() if k in wanted and isinstance(v, str) and v.strip()]


def _destination_values(decls: Any, settings: Mapping[str, Any]) -> List[str]:
    return [value for _key, value in _destination_items(decls, settings)]


def refused(decls: Any, settings: Mapping[str, Any]) -> str:
    for value in _destination_values(decls, settings):
        problems = destination_rules.refusals(value)
        if problems:
            return problems[0]
    return ""


def warnings(decls: Any, settings: Mapping[str, Any], state_dir: Path) -> List[SettingsWarning]:
    out: List[SettingsWarning] = []
    for key, value in _destination_items(decls, settings):
        sentence = destination_rules.same_disk_warning(value, state_dir)
        if sentence:
            out.append(SettingsWarning(SAME_DISK_CODE, SAME_DISK_MESSAGE, key, sentence))
    return out
