
from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.content import Content


def plain(value: Any) -> Text:
    return Text("" if value is None else str(value))


def plain_content(value: Any) -> Content:
    return Content("" if value is None else str(value))
