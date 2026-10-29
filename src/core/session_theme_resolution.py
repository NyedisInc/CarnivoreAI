
from dataclasses import dataclass
from typing import Optional

THEME_SOURCE_PIN = "pin"
THEME_SOURCE_PROJECT_DEFAULT = "project_default"
THEME_SOURCE_GLOBAL_DEFAULT = "global_default"
THEME_SOURCE_NONE = "none"


@dataclass(frozen=True)
class ThemeResolution:

    theme_id: Optional[str]
    source: str


def resolve_theme(
    pinned: Optional[str],
    project_default: Optional[str],
    global_default: Optional[str] = None,
) -> ThemeResolution:
    if pinned:
        return ThemeResolution(theme_id=pinned, source=THEME_SOURCE_PIN)
    if project_default:
        return ThemeResolution(
            theme_id=project_default,
            source=THEME_SOURCE_PROJECT_DEFAULT,
        )
    if global_default:
        return ThemeResolution(
            theme_id=global_default,
            source=THEME_SOURCE_GLOBAL_DEFAULT,
        )
    return ThemeResolution(theme_id=None, source=THEME_SOURCE_NONE)
