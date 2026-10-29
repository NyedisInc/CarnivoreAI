
from pydantic import BaseModel


UI_KEY = "ui"


class UIConfig(BaseModel):
    """
    ADDITIVE AND DEFAULT-ON. Every flag here hides something that ships
    enabled, so a config.json predating this block loads with the app
    exactly as it was. A flag that defaulted to False would silently
    remove a capability from every install that upgraded.

    Fields:
        show_mark_unread_control: Whether the manual unread toggle is
            rendered. True (shown) unless explicitly set to false.
    """

    show_mark_unread_control: bool = True
