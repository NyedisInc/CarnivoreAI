
from __future__ import annotations

from typing import Callable, FrozenSet

from src.plugins.host.ui_doc_markdown_tags import (
    ASCII_PUNCT as _ASCII_PUNCT,
    AUTOLINK_EMAIL_RE,
    AUTOLINK_URI_RE,
    HTML_OPEN_CLOSE_LINE_RE,
    HTML_TAG_RE,
    _build_comment_index,
    _is_ascii_alpha,
    _is_md_valid_autolink_url,
    _match_close_tag,
    _match_comment_with_index,
    _match_open_tag,
    _try_autolink,
    match_html_open_close_line,
    normalize_reference,
    normalize_reference_label,
    parse_link_destination,
    parse_link_title,
    unescape_commonmark_and_entities,
)

__all__ = [
    "AUTOLINK_EMAIL_RE",
    "AUTOLINK_URI_RE",
    "HTML_OPEN_CLOSE_LINE_RE",
    "HTML_TAG_RE",
    "match_html_open_close_line",
    "normalize_reference",
    "normalize_reference_label",
    "parse_link_destination",
    "parse_link_title",
    "scan_inline_violations",
    "unescape_commonmark_and_entities",
]


def _skip_ascii_ws(segment: str, pos: int, maximum: int) -> int:
    while pos < maximum and segment[pos] in (" ", "\t", "\n"):
        pos += 1
    return pos


def scan_inline_violations(
    segment: str,
    check_url: Callable[[str], str | None],
    ref_labels: FrozenSet[str] = frozenset(),
) -> str | None:
    end = len(segment)
    last_gt = segment.rfind(">")
    last_pi_close: int | None = None
    last_cdata_close: int | None = None
    comment_index: tuple[list[int], list[int], dict[int, int]] | None = None
    bt_scanned_all = False
    bt_last_pos: dict[int, int] = {}
    ref_label_cache: dict[int, int] = {}
    ref_has_nested_link_cache: set[int] = set()
    ref_has_nested_bracket_cache: set[int] = set()
    skip_link_cache: dict[int, int] = {}
    paren_cache: dict[int, tuple[int, str | None, int]] = {}

    def match_html_inline_fast(pos: int) -> int:
        nonlocal last_pi_close, last_cdata_close, comment_index
        if pos > last_gt or pos + 2 >= end:
            return -1
        ch = segment[pos + 1]
        if ch == "!":
            if segment.startswith("<!--", pos):
                if pos + 5 <= end and segment[pos + 4] == ">":
                    return pos + 5
                if pos + 6 <= end and segment[pos + 4] == "-" and segment[pos + 5] == ">":
                    return pos + 6
                if comment_index is None:
                    comment_index = _build_comment_index(segment)
                return _match_comment_with_index(pos, comment_index)
            if segment.startswith("<![CDATA[", pos):
                if last_cdata_close is None:
                    last_cdata_close = segment.rfind("]]>")
                if pos + 9 > last_cdata_close:
                    return -1
                idx = segment.find("]]>", pos + 9, end)
                return idx + 3 if idx != -1 else -1
            if _is_ascii_alpha(segment[pos + 2]):
                if pos + 3 > last_gt:
                    return -1
                idx = segment.find(">", pos + 3, end)
                return idx + 1 if idx != -1 else -1
            return -1
        if ch == "?":
            if last_pi_close is None:
                last_pi_close = segment.rfind("?>")
            if pos + 2 > last_pi_close:
                return -1
            idx = segment.find("?>", pos + 2, end)
            return idx + 2 if idx != -1 else -1
        if ch == "/":
            return _match_close_tag(segment, pos, end)
        if _is_ascii_alpha(ch):
            return _match_open_tag(segment, pos, end)
        return -1

    def find_backticks(pos: int) -> tuple[int, int]:
        nonlocal bt_scanned_all
        j = pos
        while j < end and segment[j] == "`":
            j += 1
        open_len = j - pos
        if bt_scanned_all and bt_last_pos.get(open_len, -1) <= pos:
            return j, -1
        k = j
        while k < end:
            if segment[k] == "`":
                m = k
                while m < end and segment[m] == "`":
                    m += 1
                run_len = m - k
                if run_len == open_len:
                    return j, m
                if bt_last_pos.get(run_len, -1) < k:
                    bt_last_pos[run_len] = k
                k = m
            else:
                k += 1
        bt_scanned_all = True
        return j, -1

    def try_inline_paren_tail(open_paren_pos: int) -> tuple[int, str | None, int]:
        cached = paren_cache.get(open_paren_pos)
        if cached is not None:
            return cached
        p = _skip_ascii_ws(segment, open_paren_pos + 1, end)
        if p >= end:
            res: tuple[int, str | None, int] = (-1, None, -1)
            paren_cache[open_paren_pos] = res
            return res
        dest_val: str | None = None
        ok_dest, dest_end, dest_str = parse_link_destination(segment, p, end, False)
        if ok_dest and _is_md_valid_autolink_url(dest_str):
            dest_val = dest_str
            p = dest_end
            ws_start = p
            p = _skip_ascii_ws(segment, p, end)
            if p < end and p != ws_start:
                ok_title, title_end, _ = parse_link_title(segment, p, end)
                if ok_title:
                    p = _skip_ascii_ws(segment, title_end, end)
        if p < end and segment[p] == ")":
            res = (p + 1, dest_val, -1)
        else:
            res = (-1, None, p + 1)
        paren_cache[open_paren_pos] = res
        return res

    def run_pass(start_pos: int, allow_desync_check: bool) -> tuple[str | None, int]:
        desync_from = -1
        saw_closed_span_in_openers = False
        openers: list[list[object]] = []
        active_or_img_openers = 0
        pos = start_pos
        saw_link_err = False

        def note_desync(fallback_start: int = -1) -> None:
            nonlocal desync_from
            if allow_desync_check and desync_from == -1 and saw_closed_span_in_openers:
                for op in openers:
                    if op[2] or op[1]:
                        desync_from = int(op[0]) + (2 if op[1] else 1)  # type: ignore[arg-type]
                        break
                if desync_from == -1 and fallback_start != -1:
                    desync_from = fallback_start

        def find_ref_label_end(init_bracket: int, init_fallback: int = -1) -> int:
            cached = ref_label_cache.get(init_bracket)
            if cached is not None:
                return cached
            frames: list[list[object]] = [
                [init_bracket, init_fallback, [[init_bracket, False, False, False]], init_bracket + 1, None]
            ]
            last_result = -1

            def mark_stack_failed(stack: list[list[object]]) -> None:
                for item in stack:
                    open_p = int(item[0])  # type: ignore[arg-type]
                    b_key = open_p + 1 if item[1] else open_p
                    ref_label_cache[b_key] = -1

            def propagate_nested_link(stack: list[list[object]]) -> None:
                idx = len(stack) - 1
                while idx >= 0:
                    op = stack[idx]
                    if op[2]:
                        break
                    op[2] = True
                    if op[1]:
                        break
                    idx -= 1

            def finish_inner_tail(
                frame: list[object],
                open_p: int,
                is_img: bool,
                h_link: bool,
                h_br: bool,
                label_end: int,
                p_ref: int,
                ref_end: int,
                tried_img: bool,
            ) -> None:
                stack: list[list[object]] = frame[2]  # type: ignore[assignment]
                label_start = open_p + (2 if is_img else 1)
                next_pos = (ref_end + 1) if ref_end >= 0 else (label_end + 1)
                has_nonempty_ref = ref_end >= 0 and ref_end > p_ref + 1
                matched = False
                if has_nonempty_ref:
                    if p_ref not in ref_has_nested_bracket_cache:
                        matched = normalize_reference_label(segment[p_ref + 1 : ref_end]) in ref_labels
                elif not h_br:
                    matched = normalize_reference_label(segment[label_start:label_end]) in ref_labels
                if tried_img:
                    if matched:
                        skip_link_cache[open_p] = next_pos
                        stack[-1][3] = True
                        frame[3] = next_pos
                    else:
                        skip_link_cache[open_p] = -1
                        skip_link_cache[open_p + 1] = -1
                        if h_link:
                            propagate_nested_link(stack)
                        frame[3] = label_end + 1
                    return
                link_key = open_p + 1 if is_img else open_p
                if matched:
                    skip_link_cache[link_key] = next_pos
                    stack[-1][3] = True
                    propagate_nested_link(stack)
                    frame[3] = next_pos
                else:
                    skip_link_cache[link_key] = -1
                    if is_img and h_link:
                        propagate_nested_link(stack)
                    frame[3] = label_end + 1

            def start_inner_tail(
                frame: list[object],
                open_p: int,
                is_img: bool,
                h_link: bool,
                h_br: bool,
                label_end: int,
            ) -> None:
                stack: list[list[object]] = frame[2]  # type: ignore[assignment]
                label_start = open_p + (2 if is_img else 1)
                p = label_end + 1
                if is_img:
                    if p < end and segment[p] == "(":
                        m_end, _dest_val, fb_pos = try_inline_paren_tail(p)
                        if m_end >= 0:
                            skip_link_cache[open_p] = m_end
                            stack[-1][3] = True
                            frame[3] = m_end
                            return
                        skip_link_cache[open_p] = -1
                        if h_link or fb_pos == -1 or not ref_labels:
                            skip_link_cache[open_p + 1] = -1
                            if h_link:
                                propagate_nested_link(stack)
                            frame[3] = label_end + 1
                            return
                        if fb_pos < end and segment[fb_pos] == "[":
                            c_ref = ref_label_cache.get(fb_pos)
                            if c_ref is None:
                                frame[4] = (open_p, True, h_link, h_br, label_end, fb_pos, False)
                                frames.append([fb_pos, label_start, [[fb_pos, False, False, False]], fb_pos + 1, None])
                                return
                            finish_inner_tail(frame, open_p, True, h_link, h_br, label_end, fb_pos, c_ref, False)
                            return
                        finish_inner_tail(frame, open_p, True, h_link, h_br, label_end, fb_pos, -1, False)
                        return
                    if not ref_labels:
                        skip_link_cache[open_p] = -1
                        skip_link_cache[open_p + 1] = -1
                        if h_link:
                            propagate_nested_link(stack)
                        frame[3] = label_end + 1
                        return
                    if p < end and segment[p] == "[":
                        c_ref = ref_label_cache.get(p)
                        if c_ref is None:
                            frame[4] = (open_p, True, h_link, h_br, label_end, p, True)
                            frames.append([p, label_start, [[p, False, False, False]], p + 1, None])
                            return
                        finish_inner_tail(frame, open_p, True, h_link, h_br, label_end, p, c_ref, True)
                        return
                    finish_inner_tail(frame, open_p, True, h_link, h_br, label_end, p, -1, True)
                    return

                if h_link:
                    skip_link_cache[open_p] = -1
                    propagate_nested_link(stack)
                    frame[3] = label_end + 1
                    return
                p_ref = p
                if p < end and segment[p] == "(":
                    m_end, _dest_val, fb_pos = try_inline_paren_tail(p)
                    if m_end >= 0:
                        skip_link_cache[open_p] = m_end
                        stack[-1][3] = True
                        propagate_nested_link(stack)
                        frame[3] = m_end
                        return
                    if fb_pos == -1:
                        skip_link_cache[open_p] = -1
                        frame[3] = label_end + 1
                        return
                    p_ref = fb_pos
                if not ref_labels:
                    skip_link_cache[open_p] = -1
                    frame[3] = label_end + 1
                    return
                if p_ref < end and segment[p_ref] == "[":
                    c_ref = ref_label_cache.get(p_ref)
                    if c_ref is None:
                        frame[4] = (open_p, False, h_link, h_br, label_end, p_ref, False)
                        frames.append([p_ref, label_start, [[p_ref, False, False, False]], p_ref + 1, None])
                        return
                    finish_inner_tail(frame, open_p, False, h_link, h_br, label_end, p_ref, c_ref, False)
                    return
                finish_inner_tail(frame, open_p, False, h_link, h_br, label_end, p_ref, -1, False)

            while frames:
                frame = frames[-1]
                pending = frame[4]
                if pending is not None:
                    frame[4] = None
                    op_p, is_im, h_lnk, h_brk, lbl_e, p_rf, tr_im = pending  # type: ignore[misc]
                    finish_inner_tail(frame, op_p, is_im, h_lnk, h_brk, lbl_e, p_rf, last_result, tr_im)
                    if frames[-1] is not frame:
                        continue
                stack: list[list[object]] = frame[2]  # type: ignore[assignment]
                q = int(frame[3])  # type: ignore[arg-type]
                fb_root = int(frames[0][1])  # type: ignore[arg-type]
                fb_cur = fb_root if fb_root != -1 else int(frame[1])  # type: ignore[arg-type]
                while q < end:
                    ch = segment[q]
                    if ch == "]":
                        item = stack.pop()
                        open_p = int(item[0])  # type: ignore[arg-type]
                        is_img = bool(item[1])
                        h_link = bool(item[2])
                        h_br = bool(item[3])
                        b_key = open_p + 1 if is_img else open_p
                        ref_label_cache[b_key] = q
                        if h_link:
                            ref_has_nested_link_cache.add(b_key)
                        if h_br:
                            ref_has_nested_bracket_cache.add(b_key)
                        if not stack:
                            last_result = q
                            frames.pop()
                            break
                        start_inner_tail(frame, open_p, is_img, h_link, h_br, q)
                        if frames[-1] is not frame:
                            break
                        q = int(frame[3])  # type: ignore[arg-type]
                        continue
                    if ch == "\\":
                        q += 2 if q + 1 < end else 1
                        continue
                    if ch == "`":
                        was_scanned = bt_scanned_all
                        open_e, close_e = find_backticks(q)
                        if not was_scanned and bt_scanned_all:
                            note_desync(fb_cur)
                        q = close_e if close_e != -1 else open_e
                        continue
                    if ch == "<":
                        if q <= last_gt:
                            auto = _try_autolink(segment, q, end)
                            if auto is not None and _is_md_valid_autolink_url(auto[0]):
                                q = auto[1]
                                continue
                            html_end = match_html_inline_fast(q)
                            if html_end != -1:
                                q = html_end
                                continue
                        q += 1
                        continue
                    if ch == "[":
                        skip_end = skip_link_cache.get(q)
                        if skip_end is not None and skip_end >= 0:
                            stack[-1][3] = True
                            propagate_nested_link(stack)
                            q = skip_end
                            frame[3] = q
                            continue
                        sub_cached = ref_label_cache.get(q)
                        if sub_cached is not None:
                            if sub_cached < 0:
                                mark_stack_failed(stack)
                                last_result = -1
                                frames.pop()
                                break
                            if q in skip_link_cache:
                                stack[-1][3] = True
                                if q in ref_has_nested_link_cache:
                                    propagate_nested_link(stack)
                                q = sub_cached + 1
                                frame[3] = q
                                continue
                            stack[-1][3] = True
                            start_inner_tail(
                                frame,
                                q,
                                False,
                                q in ref_has_nested_link_cache,
                                q in ref_has_nested_bracket_cache,
                                sub_cached,
                            )
                            if frames[-1] is not frame:
                                break
                            q = int(frame[3])  # type: ignore[arg-type]
                            continue
                        stack[-1][3] = True
                        stack.append([q, False, False, False])
                        q += 1
                        frame[3] = q
                        continue
                    if ch == "!" and q + 1 < end and segment[q + 1] == "[":
                        skip_end = skip_link_cache.get(q)
                        if skip_end is not None:
                            stack[-1][3] = True
                            q = skip_end if skip_end >= 0 else q + 1
                            frame[3] = q
                            continue
                        sub_cached = ref_label_cache.get(q + 1)
                        if sub_cached is not None:
                            if sub_cached < 0:
                                mark_stack_failed(stack)
                                last_result = -1
                                frames.pop()
                                break
                            stack[-1][3] = True
                            start_inner_tail(
                                frame,
                                q,
                                True,
                                (q + 1) in ref_has_nested_link_cache,
                                (q + 1) in ref_has_nested_bracket_cache,
                                sub_cached,
                            )
                            if frames[-1] is not frame:
                                break
                            q = int(frame[3])  # type: ignore[arg-type]
                            continue
                        stack[-1][3] = True
                        stack.append([q, True, False, False])
                        q += 2
                        frame[3] = q
                        continue
                    q += 1
                else:
                    mark_stack_failed(stack)
                    last_result = -1
                    frames.pop()
            return last_result

        while pos < end:
            ch = segment[pos]
            if ch == "\\":
                if pos + 1 < end and (segment[pos + 1] == "\n" or segment[pos + 1] in _ASCII_PUNCT):
                    pos += 2
                else:
                    pos += 1
                continue
            if ch == "`":
                was_scanned = bt_scanned_all
                open_end, close_end = find_backticks(pos)
                if close_end != -1:
                    if allow_desync_check and active_or_img_openers > 0:
                        saw_closed_span_in_openers = True
                elif not was_scanned and bt_scanned_all:
                    note_desync()
                pos = close_end if close_end != -1 else open_end
                continue
            if ch == "<":
                if pos <= last_gt:
                    auto = _try_autolink(segment, pos, end)
                    if auto is not None:
                        if check_url(auto[0]) == "link_not_allowed":
                            saw_link_err = True
                        pos = auto[1]
                        continue
                    if match_html_inline_fast(pos) != -1:
                        return "html_not_allowed", -1
                pos += 1
                continue
            if ch == "[":
                if openers:
                    openers[-1][3] = True
                openers.append([pos, False, True, False, False])
                active_or_img_openers += 1
                pos += 1
                continue
            if ch == "!" and pos + 1 < end and segment[pos + 1] == "[":
                if openers:
                    openers[-1][3] = True
                openers.append([pos, True, True, False, False])
                active_or_img_openers += 1
                pos += 2
                continue
            if ch == "]":
                if not openers:
                    pos += 1
                    continue
                opener = openers.pop()
                opener_pos = int(opener[0])  # type: ignore[arg-type]
                is_image = bool(opener[1])
                active = bool(opener[2])
                has_nested_bracket = bool(opener[3])
                has_nested_link = bool(opener[4])
                if active or is_image:
                    active_or_img_openers -= 1
                if not active:
                    pos += 1
                    continue

                label_start = opener_pos + (2 if is_image else 1)
                label_end = pos
                p = label_end + 1
                matched_end = -1
                matched_dest: str | None = None
                matched_as_image = False

                def try_ref_match(p_ref: int, ref_fallback: int) -> int:
                    if not ref_labels:
                        return -1
                    has_nonempty_ref = False
                    next_pos = label_end + 1
                    if p_ref < end and segment[p_ref] == "[":
                        ref_end = find_ref_label_end(p_ref, ref_fallback)
                        if ref_end >= 0:
                            next_pos = ref_end + 1
                            if ref_end > p_ref + 1:
                                has_nonempty_ref = True
                                if p_ref not in ref_has_nested_bracket_cache:
                                    if normalize_reference_label(segment[p_ref + 1 : ref_end]) in ref_labels:
                                        return next_pos
                                return -1
                    if not has_nonempty_ref and not has_nested_bracket:
                        if normalize_reference_label(segment[label_start:label_end]) in ref_labels:
                            return next_pos
                    return -1

                if p < end and segment[p] == "(":
                    cand_end, cand_dest, fb_pos = try_inline_paren_tail(p)
                    if cand_end >= 0:
                        matched_end = cand_end
                        matched_dest = cand_dest
                        matched_as_image = is_image
                    elif not has_nested_link and fb_pos != -1:
                        matched_end = try_ref_match(fb_pos, label_start)
                elif is_image:
                    matched_end = try_ref_match(p, label_start)
                    if matched_end >= 0:
                        matched_as_image = True
                elif not has_nested_link:
                    matched_end = try_ref_match(p, label_start)

                if matched_end >= 0:
                    if matched_dest is not None and check_url(matched_dest) == "link_not_allowed":
                        saw_link_err = True
                    if not matched_as_image:
                        idx_op = len(openers) - 1
                        while idx_op >= 0:
                            op = openers[idx_op]
                            if op[1]:
                                op[4] = True
                                break
                            if not op[2]:
                                break
                            op[2] = False
                            active_or_img_openers -= 1
                            idx_op -= 1
                    pos = matched_end
                    continue

                if is_image and has_nested_link:
                    idx_op = len(openers) - 1
                    while idx_op >= 0:
                        op = openers[idx_op]
                        if op[1]:
                            op[4] = True
                            break
                        if not op[2]:
                            break
                        op[2] = False
                        active_or_img_openers -= 1
                        idx_op -= 1

                pos += 1
                continue
            pos += 1

        return ("link_not_allowed" if saw_link_err else None), desync_from

    res1, desync_from = run_pass(0, True)
    if res1 == "html_not_allowed":
        return res1
    if desync_from != -1:
        ref_label_cache.clear()
        ref_has_nested_link_cache.clear()
        ref_has_nested_bracket_cache.clear()
        skip_link_cache.clear()
        res2, _ = run_pass(desync_from, False)
        if res2 == "html_not_allowed":
            return res2
        if res2 == "link_not_allowed":
            return res2
    return res1
