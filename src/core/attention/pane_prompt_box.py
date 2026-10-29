
from __future__ import annotations

from typing import Optional, Pattern, Sequence


def _is_rule_line(line: str) -> bool:
    body = line.strip()
    return bool(body) and body.count("\u2500") * 2 >= len(body)


def line_above_prompt_box(
    window: Sequence[str], lines: Sequence[str], prompt_marker: Pattern[str]
) -> Optional[str]:
    prompts = [line for line in window if prompt_marker.search(line)]
    if not prompts:
        return None
    target = prompts[-1]
    index = None
    for position in range(len(lines) - 1, -1, -1):
        if lines[position] == target:
            index = position
            break
    if index is None:
        return None
    position = index - 1
    while position >= 0 and not lines[position].strip():
        position -= 1
    if position < 0 or not _is_rule_line(lines[position]):
        return None
    position -= 1
    while position >= 0 and not lines[position].strip():
        position -= 1
    return lines[position] if position >= 0 else None


def input_box_drawn(lines: Sequence[str], prompt_marker: Pattern[str]) -> bool:
    rows = [line for line in lines if line.strip()]
    for index in range(1, len(rows) - 1):
        if (
            prompt_marker.search(rows[index])
            and _is_rule_line(rows[index - 1])
            and _is_rule_line(rows[index + 1])
        ):
            return True
    return False
