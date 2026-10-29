
from __future__ import annotations

import html
import re
from typing import Callable

LinkResolver = Callable[[str], str | None]

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)([-*])\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_CODE_SPAN = re.compile(r"(`+)(.+?)\1")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")


def slugify(text: str) -> str:
    kept = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"\s+", "-", kept.strip())


def render_inline(text: str, resolve: LinkResolver) -> str:
    out: list[str] = []
    pos = 0
    for m in _CODE_SPAN.finditer(text):
        out.append(_render_plain(text[pos:m.start()], resolve))
        out.append(f"<code>{html.escape(m.group(2).strip(), quote=False)}</code>")
        pos = m.end()
    out.append(_render_plain(text[pos:], resolve))
    return "".join(out)


def _render_plain(text: str, resolve: LinkResolver) -> str:
    parts: list[str] = []
    pos = 0
    for m in _LINK.finditer(text):
        parts.append(_emphasis(text[pos:m.start()]))
        label = _emphasis(m.group(1))
        href = resolve(m.group(2))
        parts.append(f'<a href="{html.escape(href, quote=True)}">{label}</a>' if href else label)
        pos = m.end()
    parts.append(_emphasis(text[pos:]))
    return "".join(parts)


def _emphasis(text: str) -> str:
    esc = html.escape(text, quote=False)
    esc = _BOLD.sub(r"<strong>\1</strong>", esc)
    return _ITALIC.sub(r"<em>\1</em>", esc)


def _split_row(line: str) -> list[str]:
    cells: list[str] = []
    cur: list[str] = []
    in_code = False
    for ch in line.strip():
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    cells.append("".join(cur).strip())
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells


def _marker(line: str) -> tuple[int, str, str, str] | None:
    m = _BULLET.match(line)
    if m:
        return len(m.group(1)), "ul", m.group(2), m.group(3)
    m = _NUMBER.match(line)
    if m:
        return len(m.group(1)), "ol", m.group(2), m.group(3)
    return None


class _Renderer:

    def __init__(self, resolve: LinkResolver) -> None:
        self.resolve = resolve
        self.ids: dict[str, int] = {}

    def heading_id(self, text: str) -> str:
        base = slugify(text) or "section"
        n = self.ids.get(base, 0)
        self.ids[base] = n + 1
        return base if n == 0 else f"{base}-{n}"

    def inline(self, text: str) -> str:
        return render_inline(text, self.resolve)

    def list_block(self, lines: list[str], start: int) -> tuple[str, int]:
        first = _marker(lines[start])
        assert first is not None
        base_indent, kind = first[0], first[1]
        items: list[tuple[list[str], list[str]]] = []
        i = start
        while i < len(lines):
            line = lines[i]
            mk = _marker(line)
            if mk and mk[0] == base_indent and mk[1] == kind:
                items.append(([mk[3]], []))
                i += 1
                continue
            if not line.strip():
                nxt = next((j for j in range(i + 1, len(lines)) if lines[j].strip()), None)
                if nxt is not None and items and (
                    len(lines[nxt]) - len(lines[nxt].lstrip()) > base_indent
                ):
                    i += 1
                    continue
                break
            indent = len(line) - len(line.lstrip())
            if indent <= base_indent or not items:
                break
            if mk:
                items[-1][1].append(line)
            elif items[-1][1]:
                items[-1][1].append(line)
            else:
                items[-1][0].append(line.strip())
            i += 1
        body = []
        for text_lines, nested in items:
            inner = self.inline(" ".join(text_lines))
            if nested:
                inner += "\n" + self.blocks(_dedent(nested))
            body.append(f"<li>{inner}</li>")
        return f"<{kind}>\n" + "\n".join(body) + f"\n</{kind}>", i

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            fence = re.match(r"^(\s*)(```+|~~~+)", line)
            if fence:
                end = i + 1
                code: list[str] = []
                while end < len(lines) and not lines[end].strip().startswith(fence.group(2)):
                    code.append(lines[end])
                    end += 1
                out.append("<pre><code>" + html.escape("\n".join(code), quote=False) + "</code></pre>")
                i = end + 1
                continue
            h = _HEADING.match(line)
            if h:
                level, text = len(h.group(1)), h.group(2)
                out.append(f'<h{level} id="{self.heading_id(text)}">{self.inline(text)}</h{level}>')
                i += 1
                continue
            if "|" in line and i + 1 < len(lines) and _TABLE_SEP.match(lines[i + 1]):
                head = _split_row(line)
                j = i + 2
                rows = []
                while j < len(lines) and lines[j].strip() and "|" in lines[j]:
                    rows.append(_split_row(lines[j]))
                    j += 1
                th = "".join(f"<th>{self.inline(c)}</th>" for c in head)
                trs = "".join(
                    "<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in r) + "</tr>\n" for r in rows
                )
                out.append(f'<div class="tbl"><table>\n<thead><tr>{th}</tr></thead>\n<tbody>\n{trs}</tbody>\n</table></div>')
                i = j
                continue
            if _marker(line):
                block, i = self.list_block(lines, i)
                out.append(block)
                continue
            para = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not (
                _HEADING.match(lines[i]) or _marker(lines[i]) or lines[i].lstrip().startswith("```")
            ):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{self.inline(' '.join(para))}</p>")
        return "\n".join(out)


def _dedent(lines: list[str]) -> list[str]:
    widths = [len(l) - len(l.lstrip()) for l in lines if l.strip()]
    cut = min(widths) if widths else 0
    return [l[cut:] for l in lines]


def render_markdown(text: str, resolve: LinkResolver) -> str:
    return _Renderer(resolve).blocks(text.replace("\r\n", "\n").split("\n"))
