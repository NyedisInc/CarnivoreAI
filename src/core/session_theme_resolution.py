
from dataclasses import dataclass
from typing import Optional

# could not
THEME_SOURCE_PIN = "pin"
THEME_SOURCE_PROJECT_DEFAULT = "project_default"
THEME_SOURCE_GLOBAL_DEFAULT = "global_default"
THEME_SOURCE_NONE = "none"


@dataclass(frozen=True)
class ThemeResolution:
    """The effective theme for a session, plus which store it came from.

    Attributes:
        theme_id: The theme to paint, or None when neither store holds
            one. None means "paint the app default", NOT "the stores
            could not be read" - see ``resolve_theme``.
        source: One of ``THEME_SOURCE_PIN``,
            ``THEME_SOURCE_PROJECT_DEFAULT``,
            ``THEME_SOURCE_GLOBAL_DEFAULT`` or ``THEME_SOURCE_NONE``.
    """

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
