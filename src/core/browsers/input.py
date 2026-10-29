
from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Tuple

MAX_TEXT_BYTES = 64 * 1024

MAX_KEY_LENGTH = 32

MAX_WHEEL_DELTA = 10_000.0

_MOUSE_TYPES = {
    "move": "mouseMoved",
    "down": "mousePressed",
    "up": "mouseReleased",
    "wheel": "mouseWheel",
}
_BUTTONS = frozenset({"none", "left", "middle", "right"})

INPUT_TYPES = frozenset({"mouse", "key", "text"})

Command = Tuple[str, Dict[str, Any]]


class InputRejected(ValueError):
    pass


def _number(msg: Mapping[str, Any], name: str, lo: float, hi: float, default: float = 0.0) -> float:
    value = msg.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise InputRejected(f"{name} is not a number")
    return float(min(max(value, lo), hi))


def _int(msg: Mapping[str, Any], name: str, lo: int, hi: int) -> int:
    value = msg.get(name, lo)
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise InputRejected(f"{name} is out of range")
    return value


def _short(msg: Mapping[str, Any], name: str) -> str:
    value = msg.get(name, "")
    if not isinstance(value, str) or len(value) > MAX_KEY_LENGTH:
        raise InputRejected(f"{name} is not a short string")
    return value


def map_input(msg: Mapping[str, Any], width: int, height: int) -> Command:
    kind = msg.get("type")
    modifiers = _int(msg, "modifiers", 0, 15)
    if kind == "mouse":
        event = _MOUSE_TYPES.get(msg.get("event"))
        button = msg.get("button", "none")
        if event is None or button not in _BUTTONS:
            raise InputRejected("unknown mouse event or button")
        params: Dict[str, Any] = {
            "type": event,
            "x": _number(msg, "x", 0, width),
            "y": _number(msg, "y", 0, height),
            "button": button,
            "buttons": _int(msg, "buttons", 0, 31),
            "clickCount": _int(msg, "clickCount", 0, 3),
            "modifiers": modifiers,
        }
        if event == "mouseWheel":
            params["deltaX"] = _number(msg, "deltaX", -MAX_WHEEL_DELTA, MAX_WHEEL_DELTA)
            params["deltaY"] = _number(msg, "deltaY", -MAX_WHEEL_DELTA, MAX_WHEEL_DELTA)
        return "Input.dispatchMouseEvent", params
    if kind == "key":
        event = msg.get("event")
        if event not in ("down", "up"):
            raise InputRejected("unknown key event")
        text = _short(msg, "text")
        key_code = _int(msg, "keyCode", 0, 255)
        params = {
            "key": _short(msg, "key"),
            "code": _short(msg, "code"),
            "windowsVirtualKeyCode": key_code,
            "nativeVirtualKeyCode": key_code,
            "modifiers": modifiers,
        }
        if event == "up":
            params["type"] = "keyUp"
        elif text:
            params.update(type="keyDown", text=text, unmodifiedText=text)
        else:
            params["type"] = "rawKeyDown"
        return "Input.dispatchKeyEvent", params
    if kind == "text":
        value = msg.get("value")
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_TEXT_BYTES:
            raise InputRejected("text is not a string within the size bound")
        return "Input.insertText", {"text": value}
    raise InputRejected("not an input message")
