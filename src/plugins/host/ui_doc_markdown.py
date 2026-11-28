
from __future__ import annotations

import bisect
import re
from typing import List

from src.plugins.host.ui_doc_markdown_inline import (
    match_html_open_close_line,
    normalize_reference_label,
    parse_link_destination,
    scan_inline_violations,
    unescape_commonmark_and_entities,
)

_WS_STRIP = re.compile(
    r"[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]+"
)
_SCHEME = re.compile(
    r"(^|[\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff(<\[\"'])"
    r"[A-Za-z][A-Za-z0-9+.\-]{1,20}:(//|[^\x00-\x20\x7f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff0-9])"
)
_LINK_SCHEME = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.\-]*:|//)")

_MD_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_MD_FENCE_CLOSE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_MD_BLANK_LINE = re.compile(r"^[ \t]*$")
_MD_ATX_HEADING = re.compile(r"^ {0,3}#{1,6}(?:[ \t]|$)")
_MD_ATX_STRIP = re.compile(r"^ {0,3}#{1,6}[ \t]*")
_MD_ATX_ONLY_HASH = re.compile(r"^#+[ \t]*$")
_MD_SETEXT_UNDERLINE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_MD_THEMATIC_BREAK = re.compile(r"^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$")
_MD_LIST_MARKER_ANY = re.compile(r"^ {0,3}([-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)")
_MD_LIST_MARKER_AT = re.compile(r"([-+*]|[0-9]{1,9}[.)])(?:[ \t]|$)")
_MD_LIST_MARKER_INT = re.compile(r"^ {0,3}(?:[-+*]|0{0,8}1[.)])[ \t]+[^ \t]")

_BLOCK_WS = r"[ \t\f\v\u00a0\u1680\u2000-\u200a\u202f\u205f\u3000]"
_MD_HTML_TYPE_1 = re.compile(rf"^ {{0,3}}<(?:pre|script|style|textarea)(?={_BLOCK_WS}|>|$)", re.I | re.ASCII)
_MD_HTML_TYPE_2_3_5 = re.compile(r"^ {0,3}(?:<!--|<\?|<!\[CDATA\[)")
_MD_HTML_TYPE_4 = re.compile(r"^ {0,3}<![A-Z]")
_MD_HTML_TYPE_6 = re.compile(
    r"^ {0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|"
    r"dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h1|h2|h3|h4|h5|h6|head|header|hr|html|"
    r"iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|section|summary|"
    r"table|tbody|td|tfoot|th|thead|title|tr|track|ul)" + rf"(?={_BLOCK_WS}|/>|>|$)",
    re.I | re.ASCII,
)


def _check_url(unescaped_target: str) -> str | None:
    cleaned = _WS_STRIP.sub("", unescaped_target).lstrip("<")
    if _SCHEME.search(unescaped_target) or _SCHEME.search(cleaned) or _LINK_SCHEME.match(cleaned):
        return "link_not_allowed"
    return None


def _init_line_state(line: str) -> tuple[int, int, int]:
    n = len(line)
    last_non_ws = n - 1
    while last_non_ws >= 0 and line[last_non_ws] in (" ", "\t"):
        last_non_ws -= 1
    pos = 0
    s_count = 0
    while pos < n:
        ch = line[pos]
        if ch == " ":
            s_count += 1
            pos += 1
        elif ch == "\t":
            s_count += 4 - (s_count % 4)
            pos += 1
        else:
            break
    return pos, s_count, last_non_ws


def _consume_bq_state(line: str, pos: int, s_count: int, bs_count: int, n: int) -> tuple[int, int, int]:
    old_s_count = s_count
    pos += 1
    initial = offset = old_s_count + 1
    adjust_tab = False
    space_after_marker = False
    if pos < n:
        ch = line[pos]
        if ch == " ":
            pos += 1
            initial += 1
            offset += 1
            space_after_marker = True
        elif ch == "\t":
            space_after_marker = True
            if (bs_count + offset) % 4 == 3:
                pos += 1
                initial += 1
                offset += 1
            else:
                adjust_tab = True
    while pos < n:
        ch = line[pos]
        if ch == " ":
            offset += 1
            pos += 1
        elif ch == "\t":
            offset += 4 - (offset + bs_count + (1 if adjust_tab else 0)) % 4
            pos += 1
        else:
            break
    next_bs_count = old_s_count + 1 + (1 if space_after_marker else 0)
    next_s_count = offset - initial
    return pos, next_s_count, next_bs_count


def _parse_list_marker_state(
    line: str, pos: int, s_count: int, bs_count: int, n: int
) -> tuple[int, int, int] | None:
    m = _MD_LIST_MARKER_AT.match(line, pos)
    if not m:
        return None
    marker_len = len(m.group(1))
    initial = offset = s_count + marker_len
    j = pos + marker_len
    while j < n:
        ch = line[j]
        if ch == " ":
            offset += 1
            j += 1
        elif ch == "\t":
            offset += 4 - (offset + bs_count) % 4
            j += 1
        else:
            break
    indent_after_marker = 1 if j >= n else (offset - initial)
    if indent_after_marker > 4:
        indent_after_marker = 1
    indent = initial + indent_after_marker
    return indent, j, offset


def _hr_bounds(line: str, last_non_ws: int) -> tuple[str, int, int]:
    if last_non_ws < 0:
        return "", 0, -1
    marker = line[last_non_ws]
    if marker not in ("*", "-", "_"):
        return "", 0, -1
    count = 0
    third_pos = -1
    k = last_non_ws
    while k >= 0:
        ch = line[k]
        if ch == marker:
            count += 1
            if count == 3:
                third_pos = k
        elif ch not in (" ", "\t"):
            break
        k -= 1
    if third_pos < 0:
        return "", 0, -1
    return marker, k + 1, third_pos


def _html_block_kind(stripped: str, allow_type_7: bool) -> int | None:
    if _MD_HTML_TYPE_1.match(stripped):
        return 1
    if _MD_HTML_TYPE_2_3_5.match(stripped):
        s = stripped.lstrip(" ")
        if s.startswith("<!--"):
            return 2
        if s.startswith("<?"):
            return 3
        return 5
    if _MD_HTML_TYPE_4.match(stripped):
        return 4
    if _MD_HTML_TYPE_6.match(stripped):
        return 6
    if allow_type_7 and match_html_open_close_line(stripped):
        return 7
    return None


def _atx_content(stripped: str) -> str:
    s = _MD_ATX_STRIP.sub("", stripped)
    if _MD_ATX_ONLY_HASH.match(s):
        return ""
    k = len(s)
    while k > 0 and s[k - 1] in (" ", "\t"):
        k -= 1
    h = k
    while h > 0 and s[h - 1] == "#":
        h -= 1
    if h < k and h > 0 and s[h - 1] in (" ", "\t"):
        while h > 0 and s[h - 1] in (" ", "\t"):
            h -= 1
        return s[:h]
    return s


def _match_containers(
    containers: List[tuple[str, int]],
    bq_indices: List[int],
    blk_indents: List[int],
    line: str,
    limit: int,
) -> tuple[int, int, int, int, int, int, bool]:
    n = len(line)
    pos, s_count, last_non_ws = _init_line_state(line)
    bs_count = 0
    blk_indent = 0
    matched = 0
    bq_cursor = 0
    n_bq = len(bq_indices)
    while matched < limit:
        kind, arg = containers[matched]
        if kind == "bq":
            if s_count < blk_indent or pos > last_non_ws or line[pos] != ">":
                break
            pos, s_count, bs_count = _consume_bq_state(line, pos, s_count, bs_count, n)
            blk_indent = 0
            matched += 1
            bq_cursor += 1
        elif pos > last_non_ws:
            next_bq = bq_indices[bq_cursor] if bq_cursor < n_bq else limit
            matched = next_bq if next_bq < limit else limit
            return matched, n, s_count, bs_count, blk_indents[matched], last_non_ws, True
        else:
            if s_count < arg:
                break
            blk_indent = arg
            matched += 1
    return matched, pos, s_count, bs_count, blk_indent, last_non_ws, pos > last_non_ws


def _is_terminator(
    stripped: str,
    cur_s: int,
    cur_blk: int,
    cur_list: int,
    parent_type: str,
) -> bool:
    if cur_s - cur_blk >= 4:
        return False
    mf = _MD_FENCE_OPEN.match(stripped)
    if mf and (mf.group(1)[0] == "~" or "`" not in mf.group(2)):
        return True
    if stripped.startswith(">"):
        return True
    if _MD_THEMATIC_BREAK.match(stripped):
        return True
    if _html_block_kind(stripped, allow_type_7=False) is not None:
        return True
    if _MD_ATX_HEADING.match(stripped):
        return True
    if cur_list >= 0 and cur_s - cur_list >= 4 and cur_s < cur_blk:
        return False
    if parent_type == "paragraph" and cur_s >= cur_blk:
        return bool(_MD_LIST_MARKER_INT.match(stripped))
    return bool(_MD_LIST_MARKER_ANY.match(stripped))


def _check_unmatched_terminates(
    stripped: str,
    matched: int,
    s_count: int,
    bq_indices: List[int],
    blk_indents: List[int],
    list_indents: List[int],
    parent_type: str,
) -> bool:
    has_unmatched_bq = bool(bq_indices and bq_indices[-1] >= matched)
    if not has_unmatched_bq:
        return _is_terminator(stripped, s_count, blk_indents[-1], list_indents[-1], parent_type)
    first_bq = bq_indices[bisect.bisect_left(bq_indices, matched)]
    last_bq = bq_indices[-1]
    if _is_terminator(stripped, s_count, blk_indents[first_bq], list_indents[first_bq], "blockquote"):
        return True
    if first_bq < last_bq:
        return _is_terminator(stripped, -1, 0, -1, "blockquote")
    return False


def _can_continue_ref_line(
    lines: List[str],
    idx: int,
    containers: List[tuple[str, int]],
    blk_indents: List[int],
    list_indents: List[int],
    bq_indices: List[int],
) -> tuple[str, int] | None:
    if idx >= len(lines) or _MD_BLANK_LINE.match(lines[idx]):
        return None
    raw = lines[idx]
    matched, pos, s_count, _bs, blk_indent, _lnws, is_empty_after = _match_containers(
        containers, bq_indices, blk_indents, raw, len(containers)
    )
    if is_empty_after:
        return None
    stripped = raw[pos:]
    if matched == len(containers):
        if _is_terminator(stripped, s_count, blk_indent, list_indents[-1], "reference"):
            return None
        return stripped, matched
    if _check_unmatched_terminates(
        stripped, matched, s_count, bq_indices, blk_indents, list_indents, "reference"
    ):
        return None
    return stripped, matched


def _try_parse_ref_def(
    lines: List[str],
    start_idx: int,
    first_trimmed: str,
    containers: List[tuple[str, int]],
    blk_indents: List[int],
    list_indents: List[int],
    bq_indices: List[int],
) -> tuple[str, str, int, int] | None:
    buf = first_trimmed + "\n"
    line_matched: List[int] = [len(containers)]
    next_idx = start_idx + 1

    def pull_next() -> bool:
        nonlocal buf, next_idx
        nxt = _can_continue_ref_line(lines, next_idx, containers, blk_indents, list_indents, bq_indices)
        if nxt is None:
            return False
        text_part, m_cnt = nxt
        buf += text_part + "\n"
        line_matched.append(m_cnt)
        next_idx += 1
        return True

    def line_count_at(pos: int) -> int:
        return buf[:pos].count("\n") + 1

    def skip_ws_multiline(pos: int) -> int:
        while True:
            if pos >= len(buf):
                if not pull_next():
                    return pos
            ch = buf[pos]
            if ch in (" ", "\t"):
                pos += 1
            elif ch == "\n":
                pos += 1
                if pos == len(buf) and not pull_next():
                    return pos
            else:
                return pos

    def trailing_ok(pos: int) -> bool:
        while pos < len(buf) and buf[pos] in (" ", "\t"):
            pos += 1
        return pos >= len(buf) or buf[pos] == "\n"

    pos = 1
    label_end = -1
    while True:
        if pos >= len(buf):
            if not pull_next():
                return None
        ch = buf[pos]
        if ch == "[":
            return None
        if ch == "]":
            label_end = pos
            break
        if ch == "\n":
            pos += 1
            if pos == len(buf) and not pull_next():
                return None
            continue
        if ch == "\\":
            pos += 1
            if pos >= len(buf) and not pull_next():
                return None
            if pos < len(buf) and buf[pos] == "\n":
                pos += 1
                if pos == len(buf) and not pull_next():
                    return None
                continue
        pos += 1

    if label_end < 0 or label_end + 1 >= len(buf) or buf[label_end + 1] != ":":
        return None

    pos = skip_ws_multiline(label_end + 2)
    dest_start = pos
    ok_dest, dest_end, dest_str = parse_link_destination(buf, pos, len(buf))
    if not ok_dest:
        return None

    dest_end_pos = dest_end
    final_pos = dest_end_pos
    odd_trailing_bs = False
    if dest_end_pos < len(buf) and buf[dest_end_pos] == "\n" and not buf.startswith("<", dest_start):
        bs_k = dest_end_pos
        while bs_k > dest_start and buf[bs_k - 1] == "\\":
            bs_k -= 1
        odd_trailing_bs = (dest_end_pos - bs_k) % 2 == 1

    if not odd_trailing_bs:
        after_dest_ws = skip_ws_multiline(dest_end_pos)
        if after_dest_ws > dest_end_pos and after_dest_ws < len(buf):
            opener = buf[after_dest_ws]
            if opener in ('"', "'", "("):
                closer = ")" if opener == "(" else opener
                t_pos = after_dest_ws + 1
                t_ok = False
                while True:
                    if t_pos >= len(buf):
                        if not pull_next():
                            break
                    t_ch = buf[t_pos]
                    if t_ch == closer:
                        t_pos += 1
                        t_ok = True
                        break
                    if t_ch == "(" and closer == ")":
                        break
                    if t_ch == "\\":
                        t_pos += 1
                        if t_pos >= len(buf) and not pull_next():
                            break
                    t_pos += 1
                if t_ok and trailing_ok(t_pos):
                    final_pos = t_pos

    if not trailing_ok(final_pos):
        return None

    norm_label = normalize_reference_label(buf[1:label_end])
    if not norm_label:
        return None

    used_lines = min(line_count_at(final_pos), len(line_matched))
    return dest_str, norm_label, start_idx + used_lines, line_matched[used_lines - 1]


def check_markdown_safe_violation(text: str) -> str | None:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    seg_lines: List[str] = []
    inline_segments: List[str] = []
    ref_urls: List[str] = []
    ref_labels: set[str] = set()
    containers: List[tuple[str, int]] = []
    blk_indents: List[int] = [0]
    list_indents: List[int] = [-1]
    bq_indices: List[int] = []
    in_fence: tuple[int, str, int] | None = None
    empty_li_parent: int | None = None

    def flush_seg() -> None:
        if seg_lines:
            inline_segments.append("\n".join(seg_lines))
            seg_lines.clear()

    def push_container(kind: str, arg: int) -> None:
        if kind == "bq":
            bq_indices.append(len(containers))
            list_indents.append(list_indents[-1])
            blk_indents.append(0)
        else:
            list_indents.append(blk_indents[-1])
            blk_indents.append(arg)
        containers.append((kind, arg))

    def truncate_containers(new_len: int) -> None:
        if new_len < len(containers):
            del containers[new_len:]
            del blk_indents[new_len + 1 :]
            del list_indents[new_len + 1 :]
            while bq_indices and bq_indices[-1] >= new_len:
                bq_indices.pop()

    idx = 0
    n_lines = len(lines)
    while idx < n_lines:
        raw_line = lines[idx]

        if in_fence is not None:
            f_depth, f_char, f_len = in_fence
            if _MD_BLANK_LINE.match(raw_line):
                first_bq = bq_indices[0] if bq_indices else len(containers)
                if first_bq < f_depth:
                    truncate_containers(first_bq)
                    in_fence = None
                empty_li_parent = None
                idx += 1
                continue
            matched, pos, s_count, _bs, blk_indent, _lnws, is_empty_after = _match_containers(
                containers, bq_indices, blk_indents, raw_line, f_depth
            )
            if matched < f_depth:
                truncate_containers(matched)
                in_fence = None
            else:
                if not is_empty_after and s_count - blk_indent < 4:
                    mc = _MD_FENCE_CLOSE.match(raw_line[pos:])
                    if mc and mc.group(1)[0] == f_char and len(mc.group(1)) >= f_len:
                        in_fence = None
                empty_li_parent = None
                idx += 1
                continue

        if _MD_BLANK_LINE.match(raw_line):
            flush_seg()
            limit_len = bq_indices[0] if bq_indices else len(containers)
            if empty_li_parent is not None and empty_li_parent < limit_len:
                limit_len = empty_li_parent
            truncate_containers(limit_len)
            empty_li_parent = None
            idx += 1
            continue

        matched, pos, s_count, bs_count, blk_indent, last_non_ws, is_empty_after = _match_containers(
            containers, bq_indices, blk_indents, raw_line, len(containers)
        )

        if is_empty_after:
            flush_seg()
            limit_len = matched
            if empty_li_parent is not None and empty_li_parent < limit_len:
                limit_len = empty_li_parent
            truncate_containers(limit_len)
            empty_li_parent = None
            idx += 1
            continue

        empty_li_parent = None
        stripped = raw_line[pos:]

        if seg_lines:
            if matched == len(containers):
                if s_count - blk_indent < 4:
                    if _MD_SETEXT_UNDERLINE.match(stripped) or _MD_THEMATIC_BREAK.match(stripped):
                        flush_seg()
                        idx += 1
                        continue
                    if _MD_ATX_HEADING.match(stripped):
                        flush_seg()
                        inline_segments.append(_atx_content(stripped))
                        idx += 1
                        continue
                    mf = _MD_FENCE_OPEN.match(stripped)
                    if mf and (mf.group(1)[0] == "~" or "`" not in mf.group(2)):
                        flush_seg()
                        in_fence = (len(containers), mf.group(1)[0], len(mf.group(1)))
                        idx += 1
                        continue
                    if _html_block_kind(stripped, allow_type_7=False) is not None:
                        return "html_not_allowed"
                    if stripped.startswith(">") or _MD_LIST_MARKER_INT.match(stripped):
                        flush_seg()
                    else:
                        seg_lines.append(stripped)
                        idx += 1
                        continue
                else:
                    seg_lines.append(stripped)
                    idx += 1
                    continue
            else:
                if _check_unmatched_terminates(
                    stripped, matched, s_count, bq_indices, blk_indents, list_indents, "paragraph"
                ):
                    flush_seg()
                    truncate_containers(matched)
                    blk_indent = blk_indents[matched]
                    if s_count - blk_indent >= 4:
                        idx += 1
                        continue
                else:
                    seg_lines.append(stripped)
                    idx += 1
                    continue
        else:
            truncate_containers(matched)

        n_line = len(raw_line)
        hr_info: tuple[str, int, int] | None = None
        last_pushed_kind: str | None = None
        while pos <= last_non_ws and s_count - blk_indent < 4:
            if raw_line[pos] == ">":
                pos, s_count, bs_count = _consume_bq_state(raw_line, pos, s_count, bs_count, n_line)
                blk_indent = 0
                push_container("bq", 0)
                last_pushed_kind = "bq"
                continue
            if raw_line[last_non_ws] in ("*", "-", "_"):
                if hr_info is None:
                    hr_info = _hr_bounds(raw_line, last_non_ws)
                hr_ch, hr_min, hr_third = hr_info
                if hr_third >= 0 and pos >= hr_min and pos <= hr_third and raw_line[pos] == hr_ch:
                    break
            li = _parse_list_marker_state(raw_line, pos, s_count, bs_count, n_line)
            if li is not None:
                indent, pos, s_count = li
                blk_indent = indent
                push_container("li", indent)
                last_pushed_kind = "li"
                continue
            break

        if pos > last_non_ws:
            if last_pushed_kind == "li":
                empty_li_parent = len(containers) - 1
            idx += 1
            continue

        if s_count - blk_indent >= 4:
            idx += 1
            continue

        stripped = raw_line[pos:]
        mf = _MD_FENCE_OPEN.match(stripped)
        if mf and (mf.group(1)[0] == "~" or "`" not in mf.group(2)):
            in_fence = (len(containers), mf.group(1)[0], len(mf.group(1)))
            idx += 1
            continue

        if _MD_THEMATIC_BREAK.match(stripped):
            idx += 1
            continue

        if _MD_ATX_HEADING.match(stripped):
            inline_segments.append(_atx_content(stripped))
            idx += 1
            continue

        if _html_block_kind(stripped, allow_type_7=True) is not None:
            return "html_not_allowed"

        if stripped.startswith("["):
            ref = _try_parse_ref_def(
                lines, idx, stripped, containers, blk_indents, list_indents, bq_indices
            )
            if ref is not None:
                dest_url, norm_label, next_idx, last_matched = ref
                ref_urls.append(dest_url)
                ref_labels.add(norm_label)
                truncate_containers(last_matched)
                idx = next_idx
                continue

        seg_lines.append(stripped)
        idx += 1

    flush_seg()

    frozen_refs = frozenset(ref_labels)
    saw_link_err = False
    for segment in inline_segments:
        verdict = scan_inline_violations(segment, _check_url, frozen_refs)
        if verdict == "html_not_allowed":
            return "html_not_allowed"
        if verdict == "link_not_allowed":
            saw_link_err = True

    decoded = unescape_commonmark_and_entities(normalized)
    if _SCHEME.search(decoded):
        return "link_not_allowed"
    for ref_url in ref_urls:
        if _check_url(ref_url) == "link_not_allowed":
            return "link_not_allowed"
    if saw_link_err:
        return "link_not_allowed"
    return None
