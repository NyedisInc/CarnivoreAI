
from __future__ import annotations

import bisect
import html.entities
import re

_NAMED_ENTITIES: dict[str, str] = {
    k[:-1]: v for k, v in html.entities.html5.items() if k.endswith(";")
}

ASCII_PUNCT = frozenset(r"""!"#$%&'()*+,-./:;<=>?@[\]^_`{|}~""")
_CM_UNESCAPE_RE = re.compile(
    r"""\\([!"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])|&#[xX]([0-9a-fA-F]{1,6});|&#([0-9]{1,7});|&([A-Za-z][A-Za-z0-9]{1,31});"""
)
_REF_WS_RE = re.compile(
    r"[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+"
)
_REF_WS_SINGLE_RE = re.compile(
    r"[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
)

_ATTR_WS = r"[ \t\r\n\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]"
_ATTR_NAME = r"[a-zA-Z_:][a-zA-Z0-9:._-]*"
_UNQUOTED = r"[^\"'=<>`\x00-\x20\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+"
_SINGLE_QUOTED = r"'[^']*'"
_DOUBLE_QUOTED = r'"[^"]*"'
_ATTR_VALUE = rf"(?:{_UNQUOTED}|{_SINGLE_QUOTED}|{_DOUBLE_QUOTED})"
_ATTRIBUTE = rf"(?:{_ATTR_WS}+{_ATTR_NAME}(?:{_ATTR_WS}*={_ATTR_WS}*{_ATTR_VALUE})?)"
_OPEN_TAG = rf"<[A-Za-z][A-Za-z0-9\-]*{_ATTRIBUTE}*{_ATTR_WS}*/?>"
_CLOSE_TAG = rf"</[A-Za-z][A-Za-z0-9\-]*{_ATTR_WS}*>"
_COMMENT = r"<!---?>|<!--(?:[^-]|-[^-]|--[^>])*-->"
_PROCESSING = r"<\?[\s\S]*?\?>"
_DECLARATION = r"<![A-Za-z][^>]*>"
_CDATA = r"<!\[CDATA\[[\s\S]*?\]\]>"

HTML_TAG_RE = re.compile(
    rf"(?:{_OPEN_TAG}|{_CLOSE_TAG}|{_COMMENT}|{_PROCESSING}|{_DECLARATION}|{_CDATA})"
)
HTML_OPEN_CLOSE_LINE_RE = re.compile(
    rf"^ {{0,3}}(?:{_OPEN_TAG}|{_CLOSE_TAG}){_ATTR_WS}*$"
)

_ATTR_WS_CHARS = frozenset(
    " \t\r\n\f\v\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000"
)
_UNQUOTED_FORBIDDEN = frozenset("\"'=<>`")

_B_END_NO_WS = 1 << 0
_B_READY_WS = 1 << 1
_B_SLASH = 1 << 2
_B_IN_NAME = 1 << 3
_B_AFTER_NAME_WS = 1 << 4
_B_AFTER_EQ_WS = 1 << 5
_B_IN_UNQUOTED = 1 << 6
_B_IN_SQUOTE = 1 << 7
_B_IN_DQUOTE = 1 << 8

AUTOLINK_URI_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^\x00-\x20<>]*$")
AUTOLINK_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)
_BAD_AUTOLINK_PROTO_RE = re.compile(r"^(?:vbscript|javascript|file|data):", re.IGNORECASE)
_GOOD_AUTOLINK_DATA_RE = re.compile(r"^data:image/(?:gif|png|jpeg|webp);", re.IGNORECASE)


def _is_md_valid_autolink_url(url: str) -> bool:
    u = url.strip()
    if _BAD_AUTOLINK_PROTO_RE.match(u):
        return bool(_GOOD_AUTOLINK_DATA_RE.match(u))
    return True


def unescape_commonmark_and_entities(text: str) -> str:

    def _replace(match: re.Match[str]) -> str:
        punct = match.group(1)
        if punct is not None:
            return punct
        hex_digits = match.group(2)
        if hex_digits is not None:
            cp = int(hex_digits, 16)
            return "\ufffd" if (cp == 0 or cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF) else chr(cp)
        dec_digits = match.group(3)
        if dec_digits is not None:
            cp = int(dec_digits, 10)
            return "\ufffd" if (cp == 0 or cp > 0x10FFFF or 0xD800 <= cp <= 0xDFFF) else chr(cp)
        named = match.group(4)
        if named is not None and named in _NAMED_ENTITIES:
            return _NAMED_ENTITIES[named]
        return match.group(0)

    return _CM_UNESCAPE_RE.sub(_replace, text)


def normalize_reference(label: str) -> str:
    collapsed = _REF_WS_RE.sub(" ", _REF_WS_RE.sub(lambda m: "" if m.start() == 0 or m.end() == len(label) else " ", label))
    return collapsed.lower().upper()


def _strip_ref_ws(label: str) -> str:
    start = 0
    end = len(label)
    while start < end and _REF_WS_SINGLE_RE.match(label[start]):
        start += 1
    while end > start and _REF_WS_SINGLE_RE.match(label[end - 1]):
        end -= 1
    return _REF_WS_RE.sub(" ", label[start:end])


def normalize_reference_label(label: str) -> str:
    return _strip_ref_ws(label).lower().upper()


def parse_link_destination(
    text: str, pos: int, maximum: int, stop_before_ctrl: bool = True
) -> tuple[bool, int, str]:
    start = pos
    if pos >= maximum:
        return False, pos, ""

    if text[pos] == "<":
        pos += 1
        while pos < maximum:
            ch = text[pos]
            if ch == "\n" or ch == "<":
                return False, start, ""
            if ch == ">":
                return True, pos + 1, unescape_commonmark_and_entities(text[start + 1 : pos])
            if ch == "\\" and pos + 1 < maximum:
                if stop_before_ctrl and ord(text[pos + 1]) == 0x0A:
                    return False, start, ""
                pos += 2
                continue
            pos += 1
        return False, start, ""

    level = 0
    while pos < maximum:
        code = ord(text[pos])
        if code <= 0x20 or code == 0x7F:
            break
        if code == 0x5C and pos + 1 < maximum:
            nxt = ord(text[pos + 1])
            if nxt == 0x20:
                break
            if stop_before_ctrl and (nxt < 0x20 or nxt == 0x7F):
                pos += 1
                break
            pos += 2
            continue
        if code == 0x28:
            level += 1
            if level > 32:
                return False, start, ""
        elif code == 0x29:
            if level == 0:
                break
            level -= 1
        pos += 1

    if start == pos or level != 0:
        return False, start, ""
    return True, pos, unescape_commonmark_and_entities(text[start:pos])


def parse_link_title(text: str, pos: int, maximum: int) -> tuple[bool, int, str]:
    if pos >= maximum:
        return False, pos, ""
    opener = text[pos]
    if opener not in ('"', "'", "("):
        return False, pos, ""
    closer = ")" if opener == "(" else opener
    start = pos + 1
    pos = start
    while pos < maximum:
        ch = text[pos]
        if ch == closer:
            return True, pos + 1, unescape_commonmark_and_entities(text[start:pos])
        if ch == "(" and closer == ")":
            return False, start - 1, ""
        if ch == "\\" and pos + 1 < maximum:
            pos += 2
            continue
        pos += 1
    return False, start - 1, ""


def _try_autolink(segment: str, pos: int, maximum: int) -> tuple[str, int] | None:
    k = pos + 1
    while k < maximum:
        ch = segment[k]
        if ch == "<" or ch == "\n":
            return None
        if ch == ">":
            inner = segment[pos + 1 : k]
            if AUTOLINK_URI_RE.match(inner):
                return inner, k + 1
            if AUTOLINK_EMAIL_RE.match(inner):
                return "mailto:" + inner, k + 1
            return None
        k += 1
    return None


def _is_ascii_alpha(ch: str) -> bool:
    o = ord(ch)
    return (65 <= o <= 90) or (97 <= o <= 122)


def _is_tag_name_cont(ch: str) -> bool:
    o = ord(ch)
    return (65 <= o <= 90) or (97 <= o <= 122) or (48 <= o <= 57) or o == 45


def _is_attr_name_start(ch: str) -> bool:
    o = ord(ch)
    return (65 <= o <= 90) or (97 <= o <= 122) or o == 95 or o == 58


def _is_attr_name_cont(ch: str) -> bool:
    o = ord(ch)
    return (65 <= o <= 90) or (97 <= o <= 122) or (48 <= o <= 57) or o in (58, 46, 95, 45)


def _is_unquoted_char(ch: str) -> bool:
    return ord(ch) > 0x20 and ch not in _UNQUOTED_FORBIDDEN


def _match_open_tag(text: str, pos: int, maximum: int) -> int:
    if pos + 2 >= maximum or text[pos] != "<" or not _is_ascii_alpha(text[pos + 1]):
        return -1
    p = pos + 2
    while p < maximum and _is_tag_name_cont(text[p]):
        p += 1
    mask = _B_END_NO_WS
    while p < maximum and mask:
        if mask & _B_IN_SQUOTE:
            q = text.find("'", p, maximum)
            if q == -1:
                return -1
            p = q + 1
            mask = _B_END_NO_WS
            continue
        if mask & _B_IN_DQUOTE:
            q = text.find('"', p, maximum)
            if q == -1:
                return -1
            p = q + 1
            mask = _B_END_NO_WS
            continue
        ch = text[p]
        if ch == ">":
            if mask & (_B_END_NO_WS | _B_READY_WS | _B_SLASH | _B_IN_NAME | _B_IN_UNQUOTED):
                return p + 1
            return -1
        nxt = 0
        is_ws = ch in _ATTR_WS_CHARS
        is_unq = _is_unquoted_char(ch)
        if mask & _B_END_NO_WS:
            if is_ws:
                nxt |= _B_READY_WS
            elif ch == "/":
                nxt |= _B_SLASH
        if mask & _B_READY_WS:
            if is_ws:
                nxt |= _B_READY_WS
            elif ch == "/":
                nxt |= _B_SLASH
            elif _is_attr_name_start(ch):
                nxt |= _B_IN_NAME
        if mask & _B_IN_NAME:
            if _is_attr_name_cont(ch):
                nxt |= _B_IN_NAME
            if is_ws:
                nxt |= _B_READY_WS | _B_AFTER_NAME_WS
            elif ch == "=":
                nxt |= _B_AFTER_EQ_WS
            elif ch == "/":
                nxt |= _B_SLASH
        if mask & _B_AFTER_NAME_WS:
            if is_ws:
                nxt |= _B_AFTER_NAME_WS
            elif ch == "=":
                nxt |= _B_AFTER_EQ_WS
        if mask & _B_AFTER_EQ_WS:
            if is_ws:
                nxt |= _B_AFTER_EQ_WS
            if is_unq:
                nxt |= _B_IN_UNQUOTED
            elif ch == "'":
                nxt |= _B_IN_SQUOTE
            elif ch == '"':
                nxt |= _B_IN_DQUOTE
        if mask & _B_IN_UNQUOTED:
            if is_unq:
                nxt |= _B_IN_UNQUOTED
            if is_ws:
                nxt |= _B_READY_WS
            elif ch == "/":
                nxt |= _B_SLASH
        mask = nxt
        p += 1
    return -1


def _match_close_tag(text: str, pos: int, maximum: int) -> int:
    if pos + 3 >= maximum or text[pos] != "<" or text[pos + 1] != "/" or not _is_ascii_alpha(text[pos + 2]):
        return -1
    p = pos + 3
    while p < maximum and _is_tag_name_cont(text[p]):
        p += 1
    while p < maximum and text[p] in _ATTR_WS_CHARS:
        p += 1
    return p + 1 if (p < maximum and text[p] == ">") else -1


def match_html_open_close_line(line: str) -> bool:
    n = len(line)
    pos = 0
    while pos < n and pos < 3 and line[pos] == " ":
        pos += 1
    if pos + 2 >= n or line[pos] != "<":
        return False
    end_pos = _match_close_tag(line, pos, n) if line[pos + 1] == "/" else _match_open_tag(line, pos, n)
    if end_pos == -1:
        return False
    while end_pos < n:
        if line[end_pos] not in _ATTR_WS_CHARS:
            return False
        end_pos += 1
    return True


def _build_comment_index(segment: str) -> tuple[list[int], list[int], dict[int, int]]:
    n = len(segment)
    gen_d_starts: list[int] = []
    gen_ends: list[int] = []
    local_ends: dict[int, int] = {}
    search = 0
    while search < n:
        idx = segment.find("-->", search)
        if idx == -1:
            break
        d_start = idx
        while d_start > 0 and segment[d_start - 1] == "-":
            d_start -= 1
        d_all = (idx + 2) - d_start
        if (d_all - 2) % 3 == 0:
            gen_d_starts.append(d_start)
            gen_ends.append(idx + 3)
        elif d_all >= 4 and (d_all - 4) % 3 == 0:
            if d_start >= 2 and segment[d_start - 2] == "<" and segment[d_start - 1] == "!":
                local_pos = d_start - 2
                if local_pos not in local_ends:
                    local_ends[local_pos] = idx + 3
        search = idx + 3
    return gen_d_starts, gen_ends, local_ends


def _match_comment_with_index(pos: int, index: tuple[list[int], list[int], dict[int, int]]) -> int:
    gen_d_starts, gen_ends, local_ends = index
    best = local_ends.get(pos, -1)
    i = bisect.bisect_left(gen_d_starts, pos + 4)
    if i < len(gen_ends):
        cand = gen_ends[i]
        if best == -1 or cand < best:
            best = cand
    return best


def _match_html_inline(segment: str, pos: int, maximum: int) -> int:
    if pos + 2 >= maximum:
        return -1
    ch = segment[pos + 1]
    if ch == "/":
        return _match_close_tag(segment, pos, maximum)
    if _is_ascii_alpha(ch):
        return _match_open_tag(segment, pos, maximum)
    if ch not in ("!", "?"):
        return -1
    m = HTML_TAG_RE.match(segment, pos)
    return m.end() if m is not None else -1
