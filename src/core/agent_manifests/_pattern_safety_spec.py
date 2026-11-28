
from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


class UnsupportedRegexCategory(ValueError):
    pass


MAX_PATTERN_LEN = 256
MAX_REPEAT_BOUND = 64
MAX_TOTAL_REPEATS = 8
MAX_OPTIONALS = 4
MAX_BRANCH_PATHS = 16
MAX_UNANCHORED_WHOLE_BOUND = 8
MAX_UNANCHORED_REPEATS = 3
MAX_POST_D2_ATOMS = 4
MAX_POST_D2_AT = 1
MAX_POST_UNANCHORED_ATOMS = 4
MAX_POST_UNANCHORED_AT = 1
MAX_POST_UNANCHORED_PREFIX_LITERALS = 24
MAX_SIMPLE_POSITIVE_ATOM = 64
MAX_RANGE_BROAD = 32
MAX_CAPTURING_GROUPS = 4
MAX_AT_ASSERTIONS = 8
MAX_NON_BOUNDARY_ASSERTIONS = 1

_ALLOWED_OPCODES = frozenset(
    {
        "AT",
        "LITERAL",
        "NOT_LITERAL",
        "IN",
        "ANY",
        "SUBPATTERN",
        "BRANCH",
        "MAX_REPEAT",
        "MIN_REPEAT",
        "POSSESSIVE_REPEAT",
    }
)
_ALLOWED_IN_SUBOPCODES = frozenset({"NEGATE", "LITERAL", "RANGE", "CATEGORY"})
_ALLOWED_AT_CODES = frozenset(
    {
        "AT_BEGINNING",
        "AT_BEGINNING_LINE",
        "AT_BEGINNING_STRING",
        "AT_BOUNDARY",
        "AT_NON_BOUNDARY",
        "AT_END",
        "AT_END_LINE",
        "AT_END_STRING",
        "AT_LOC_BOUNDARY",
        "AT_LOC_NON_BOUNDARY",
        "AT_UNI_BOUNDARY",
        "AT_UNI_NON_BOUNDARY",
    }
)
_NON_BOUNDARY_AT_CODES = frozenset(
    {"AT_NON_BOUNDARY", "AT_LOC_NON_BOUNDARY", "AT_UNI_NON_BOUNDARY"}
)
_ALLOWED_CATEGORIES = frozenset(
    {
        "CATEGORY_DIGIT",
        "CATEGORY_NOT_DIGIT",
        "CATEGORY_SPACE",
        "CATEGORY_NOT_SPACE",
        "CATEGORY_WORD",
        "CATEGORY_NOT_WORD",
        "CATEGORY_LINEBREAK",
        "CATEGORY_NOT_LINEBREAK",
        "CATEGORY_LOC_WORD",
        "CATEGORY_LOC_NOT_WORD",
        "CATEGORY_UNI_DIGIT",
        "CATEGORY_UNI_NOT_DIGIT",
        "CATEGORY_UNI_SPACE",
        "CATEGORY_UNI_NOT_SPACE",
        "CATEGORY_UNI_WORD",
        "CATEGORY_UNI_NOT_WORD",
        "CATEGORY_UNI_LINEBREAK",
        "CATEGORY_UNI_NOT_LINEBREAK",
    }
)

_MAX_CODEPOINT = 0x10FFFF
_ASCII_SPACE_INTERVALS: Tuple[Tuple[int, int], ...] = ((9, 13), (32, 32))
_ASCII_DIGIT_INTERVALS: Tuple[Tuple[int, int], ...] = ((48, 57),)
_ASCII_WORD_INTERVALS: Tuple[Tuple[int, int], ...] = ((48, 57), (65, 90), (95, 95), (97, 122))
_LINEBREAK_INTERVALS: Tuple[Tuple[int, int], ...] = ((10, 10),)


def _merge_intervals(intervals: Iterable[Tuple[int, int]]) -> Tuple[Tuple[int, int], ...]:
    ordered = sorted(intervals)
    if not ordered:
        return ()
    merged: List[Tuple[int, int]] = [ordered[0]]
    for lo, hi in ordered[1:]:
        prev_lo, prev_hi = merged[-1]
        if lo <= prev_hi + 1:
            if hi > prev_hi:
                merged[-1] = (prev_lo, hi)
        else:
            merged.append((lo, hi))
    return tuple(merged)


def _complement_intervals(intervals: Sequence[Tuple[int, int]]) -> Tuple[Tuple[int, int], ...]:
    out: List[Tuple[int, int]] = []
    cur = 0
    for lo, hi in intervals:
        if cur < lo:
            out.append((cur, lo - 1))
        if hi + 1 > cur:
            cur = hi + 1
    if cur <= _MAX_CODEPOINT:
        out.append((cur, _MAX_CODEPOINT))
    return tuple(out)


def _intervals_overlap(a: Sequence[Tuple[int, int]], b: Sequence[Tuple[int, int]]) -> bool:
    i = 0
    j = 0
    na = len(a)
    nb = len(b)
    while i < na and j < nb:
        lo1, hi1 = a[i]
        lo2, hi2 = b[j]
        if hi1 < lo2:
            i += 1
        elif hi2 < lo1:
            j += 1
        else:
            return True
    return False


@lru_cache(maxsize=1)
def _unicode_ic_data() -> Tuple[Dict[int, Tuple[int, ...]], Tuple[int, ...], Tuple[Tuple[int, ...], ...]]:
    try:
        import _sre  # type: ignore[import-not-found]
        from re import _casefix as _re_casefix  # type: ignore[attr-defined]

        tolower = _sre.unicode_tolower
        extra_cases: Mapping[int, Sequence[int]] = _re_casefix._EXTRA_CASES
    except (ImportError, AttributeError):  # pragma: no cover
        tolower = None
        extra_cases = {}

    if tolower is not None:
        buckets: Dict[int, set[int]] = {}
        for cp in range(_MAX_CODEPOINT + 1):
            lo = tolower(cp)
            if lo != cp:
                buckets.setdefault(lo, {lo}).add(cp)
            elif cp in extra_cases:
                buckets.setdefault(cp, {cp})
        for cp, extras in extra_cases.items():
            lo = tolower(cp)
            merged = set(buckets.get(lo, {lo}))
            for ex in extras:
                elo = tolower(ex)
                merged.update(buckets.get(elo, {elo}))
            for m in merged:
                buckets[tolower(m)] = merged
        by_cp: Dict[int, Tuple[int, ...]] = {}
        for grp in buckets.values():
            if len(grp) > 1:
                tup = tuple(sorted(grp))
                for cp in tup:
                    by_cp[cp] = tup
    else:  # pragma: no cover
        by_cp = {}
        for cp in range(_MAX_CODEPOINT + 1):
            ch = chr(cp)
            grp = {cp}
            for s in (ch.lower(), ch.upper(), ch.swapcase()):
                if len(s) == 1:
                    grp.add(ord(s))
            if len(grp) > 1:
                tup = tuple(sorted(grp))
                for m in tup:
                    by_cp[m] = tup

    cased_cps = tuple(sorted(by_cp))
    cased_groups = tuple(by_cp[cp] for cp in cased_cps)
    return by_cp, cased_cps, cased_groups


def _ic_variants(cp: int, ascii_only: bool = False) -> Tuple[int, ...]:
    if ascii_only:
        if 65 <= cp <= 90:
            return (cp, cp + 32)
        if 97 <= cp <= 122:
            return (cp - 32, cp)
        return (cp,)
    by_cp, _, _ = _unicode_ic_data()
    return by_cp.get(cp, (cp,))


def _ic_range_intervals(lo: int, hi: int, ascii_only: bool = False) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = [(lo, hi)]
    if ascii_only:
        u_lo, u_hi = max(lo, 65), min(hi, 90)
        if u_lo <= u_hi:
            out.append((u_lo + 32, u_hi + 32))
        l_lo, l_hi = max(lo, 97), min(hi, 122)
        if l_lo <= l_hi:
            out.append((l_lo - 32, l_hi - 32))
        return out
    _, cased_cps, cased_groups = _unicode_ic_data()
    idx_start = bisect_left(cased_cps, lo)
    idx_end = bisect_right(cased_cps, hi)
    for idx in range(idx_start, idx_end):
        for v in cased_groups[idx]:
            if v < lo or v > hi:
                out.append((v, v))
    return out


@lru_cache(maxsize=1)
def _unicode_category_tables() -> Tuple[
    Tuple[Tuple[int, int], ...],
    Tuple[Tuple[int, int], ...],
    Tuple[Tuple[int, int], ...],
]:
    all_chars = "".join(map(chr, range(_MAX_CODEPOINT + 1)))
    space = tuple((m.start(), m.end() - 1) for m in re.finditer(r"\s+", all_chars))
    digit = tuple((m.start(), m.end() - 1) for m in re.finditer(r"\d+", all_chars))
    word = tuple((m.start(), m.end() - 1) for m in re.finditer(r"\w+", all_chars))
    return space, digit, word


@lru_cache(maxsize=None)
def _category_intervals(cat_name: str, ascii_only: bool = False) -> Tuple[Tuple[int, int], ...]:
    if cat_name in ("CATEGORY_LINEBREAK", "CATEGORY_UNI_LINEBREAK"):
        return _LINEBREAK_INTERVALS
    if cat_name in ("CATEGORY_NOT_LINEBREAK", "CATEGORY_UNI_NOT_LINEBREAK"):
        return _complement_intervals(_LINEBREAK_INTERVALS)
    if ascii_only:
        if cat_name in ("CATEGORY_SPACE", "CATEGORY_UNI_SPACE"):
            return _ASCII_SPACE_INTERVALS
        if cat_name in ("CATEGORY_NOT_SPACE", "CATEGORY_UNI_NOT_SPACE"):
            return _complement_intervals(_ASCII_SPACE_INTERVALS)
        if cat_name in ("CATEGORY_DIGIT", "CATEGORY_UNI_DIGIT"):
            return _ASCII_DIGIT_INTERVALS
        if cat_name in ("CATEGORY_NOT_DIGIT", "CATEGORY_UNI_NOT_DIGIT"):
            return _complement_intervals(_ASCII_DIGIT_INTERVALS)
        if cat_name in ("CATEGORY_WORD", "CATEGORY_UNI_WORD", "CATEGORY_LOC_WORD"):
            return _ASCII_WORD_INTERVALS
        if cat_name in ("CATEGORY_NOT_WORD", "CATEGORY_UNI_NOT_WORD", "CATEGORY_LOC_NOT_WORD"):
            return _complement_intervals(_ASCII_WORD_INTERVALS)
    else:
        space, digit, word = _unicode_category_tables()
        if cat_name in ("CATEGORY_SPACE", "CATEGORY_UNI_SPACE"):
            return space
        if cat_name in ("CATEGORY_NOT_SPACE", "CATEGORY_UNI_NOT_SPACE"):
            return _complement_intervals(space)
        if cat_name in ("CATEGORY_DIGIT", "CATEGORY_UNI_DIGIT"):
            return digit
        if cat_name in ("CATEGORY_NOT_DIGIT", "CATEGORY_UNI_NOT_DIGIT"):
            return _complement_intervals(digit)
        if cat_name in ("CATEGORY_WORD", "CATEGORY_UNI_WORD", "CATEGORY_LOC_WORD"):
            return word
        if cat_name in ("CATEGORY_NOT_WORD", "CATEGORY_UNI_NOT_WORD", "CATEGORY_LOC_NOT_WORD"):
            return _complement_intervals(word)
    raise UnsupportedRegexCategory(f"unsupported regex category {cat_name}")


def _unwrap_single_atom(items: Iterable, flags: int) -> Tuple[Optional[Tuple[Any, Any]], int]:
    item_list = list(items)
    while len(item_list) == 1 and str(item_list[0][0]) == "SUBPATTERN":
        _gid, add_f, del_f, sub = item_list[0][1]
        flags = (flags | add_f) & ~del_f
        item_list = list(sub)
    if len(item_list) == 1 and str(item_list[0][0]) in ("LITERAL", "NOT_LITERAL", "IN", "ANY"):
        return item_list[0], flags
    return None, flags


def _is_space_category_atom(atom: Optional[Tuple[Any, Any]]) -> bool:
    if atom is None:
        return False
    op, av = atom
    if str(op) != "IN":
        return False
    items = list(av)
    return (
        len(items) == 1
        and str(items[0][0]) == "CATEGORY"
        and str(items[0][1]) in ("CATEGORY_SPACE", "CATEGORY_UNI_SPACE")
    )


def _atom_spec_detail(
    atom: Tuple[Any, Any],
    flags: int,
    *,
    error_cls: type[Exception] = ValueError,
) -> Tuple[Tuple[Tuple[int, int], ...], bool, bool, bool]:
    op, av = atom
    name = str(op)
    ignorecase = bool(flags & re.IGNORECASE)
    dotall = bool(flags & re.DOTALL)
    ascii_only = bool(flags & re.ASCII)

    if name == "ANY":
        intervals = ((0, _MAX_CODEPOINT),) if dotall else ((0, 9), (11, _MAX_CODEPOINT))
        return intervals, True, False, False

    if name == "LITERAL":
        if ignorecase:
            intervals = _merge_intervals((v, v) for v in _ic_variants(av, ascii_only))
        else:
            intervals = ((av, av),)
        return intervals, False, True, False

    if name == "NOT_LITERAL":
        if ignorecase:
            excluded = _merge_intervals((v, v) for v in _ic_variants(av, ascii_only))
        else:
            excluded = ((av, av),)
        return _complement_intervals(excluded), True, False, False

    if name == "IN":
        neg = False
        categories: List[str] = []
        raw_intervals: List[Tuple[int, int]] = []
        has_large_range = False
        total_range_len = 0
        has_non_bmp = False
        has_range = False
        has_non_ascii_lit_or_range = False
        lit_count = 0
        for sop, sav in av:
            sname = str(sop)
            if sname not in _ALLOWED_IN_SUBOPCODES:
                raise error_cls(f"unsupported regex IN sub-opcode {sname}")
            if sname == "NEGATE":
                neg = True
            elif sname == "LITERAL":
                lit_count += 1
                if sav >= 0x10000:
                    has_non_bmp = True
                if sav > 127:
                    has_non_ascii_lit_or_range = True
                if ignorecase:
                    for v in _ic_variants(sav, ascii_only):
                        raw_intervals.append((v, v))
                        if v >= 0x10000:
                            has_non_bmp = True
                        if v > 127:
                            has_non_ascii_lit_or_range = True
                else:
                    raw_intervals.append((sav, sav))
            elif sname == "RANGE":
                lo, hi = sav
                has_range = True
                if hi >= 0x10000:
                    has_non_bmp = True
                if hi > 127:
                    has_non_ascii_lit_or_range = True
                span = hi - lo + 1
                total_range_len += span
                if span > MAX_RANGE_BROAD:
                    has_large_range = True
                if ignorecase:
                    ic_ints = _ic_range_intervals(lo, hi, ascii_only)
                    raw_intervals.extend(ic_ints)
                    for _ilo, ihi in ic_ints:
                        if ihi >= 0x10000:
                            has_non_bmp = True
                        if ihi > 127:
                            has_non_ascii_lit_or_range = True
                else:
                    raw_intervals.append((lo, hi))
            elif sname == "CATEGORY":
                cat_name = str(sav)
                if cat_name not in _ALLOWED_CATEGORIES:
                    raise error_cls(f"unsupported regex category {cat_name}")
                categories.append(cat_name)
                raw_intervals.extend(_category_intervals(cat_name, ascii_only))

        merged = _merge_intervals(raw_intervals)
        intervals = _complement_intervals(merged) if neg else merged
        ascii_hits = sum(min(hi, 127) - lo + 1 for lo, hi in intervals if lo <= 127)
        total_matched = sum(hi - lo + 1 for lo, hi in intervals)
        has_category = bool(categories)
        cat_count = len(categories)
        has_dup_category = cat_count != len(set(categories))
        has_compound = cat_count > 1 or lit_count > 0 or has_range
        minimal_neg_cat = (
            neg
            and has_category
            and cat_count <= 2
            and not has_dup_category
            and not has_range
            and not has_non_ascii_lit_or_range
            and lit_count <= 1
        )
        linear_in = (
            has_non_bmp
            or cat_count > 2
            or has_dup_category
            or (neg and has_category and not minimal_neg_cat)
        )
        is_broad = (
            has_large_range
            or total_range_len > 64
            or ascii_hits > 64
            or total_matched > 200_000
            or linear_in
            or (ignorecase and has_category and (neg or (total_matched > 64_000 and has_compound)))
        )
        simple_positive = (
            (not neg)
            and (not has_category)
            and (not is_broad)
            and (total_matched <= MAX_SIMPLE_POSITIVE_ATOM)
        )
        return intervals, is_broad, simple_positive, linear_in

    raise error_cls(f"unsupported regex construct {name}")


def _atom_spec(
    atom: Tuple[Any, Any],
    flags: int,
    *,
    error_cls: type[Exception] = ValueError,
) -> Tuple[Tuple[Tuple[int, int], ...], bool, bool]:
    intervals, is_broad, simple_positive, _linear_in = _atom_spec_detail(
        atom, flags, error_cls=error_cls
    )
    return intervals, is_broad, simple_positive


def _specs_overlap(
    s1: Optional[Tuple[Tuple[int, int], ...]],
    s2: Optional[Tuple[Tuple[int, int], ...]],
) -> bool:
    if s1 is None or s2 is None:
        return True
    return _intervals_overlap(s1, s2)


def _contains_broad(
    items: Iterable,
    flags: int,
    *,
    error_cls: type[Exception] = ValueError,
) -> bool:
    for op, av in items:
        name = str(op)
        if name not in _ALLOWED_OPCODES:
            raise error_cls(f"unsupported regex construct {name}")
        if name in ("ANY", "NOT_LITERAL", "IN"):
            _, b, _ = _atom_spec((op, av), flags, error_cls=error_cls)
            if b:
                return True
        elif name == "SUBPATTERN":
            _gid, add_f, del_f, sub = av
            if _contains_broad(sub, (flags | add_f) & ~del_f, error_cls=error_cls):
                return True
        elif name == "BRANCH":
            if any(_contains_broad(b, flags, error_cls=error_cls) for b in av[1]):
                return True
        elif name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            if _contains_broad(av[2], flags, error_cls=error_cls):
                return True
    return False


def _contains_linear_in(
    items: Iterable,
    flags: int,
    *,
    error_cls: type[Exception] = ValueError,
) -> bool:
    for op, av in items:
        name = str(op)
        if name not in _ALLOWED_OPCODES:
            raise error_cls(f"unsupported regex construct {name}")
        if name in ("ANY", "NOT_LITERAL", "IN"):
            _, _, _, linear_in = _atom_spec_detail((op, av), flags, error_cls=error_cls)
            if linear_in:
                return True
        elif name == "SUBPATTERN":
            _gid, add_f, del_f, sub = av
            if _contains_linear_in(sub, (flags | add_f) & ~del_f, error_cls=error_cls):
                return True
        elif name == "BRANCH":
            if any(_contains_linear_in(b, flags, error_cls=error_cls) for b in av[1]):
                return True
        elif name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            if _contains_linear_in(av[2], flags, error_cls=error_cls):
                return True
    return False


def _is_literal_only_optional(
    items: Iterable,
    *,
    allow_one_capture: bool = True,
    error_cls: type[Exception] = ValueError,
) -> Tuple[bool, int, int]:
    item_list = list(items)
    if not item_list:
        return False, 0, 0
    cap_count = 0
    if len(item_list) == 1 and str(item_list[0][0]) == "SUBPATTERN":
        gid, add_f, del_f, sub = item_list[0][1]
        if add_f != 0 or del_f != 0:
            return False, 0, 0
        if gid is not None:
            if not allow_one_capture:
                return False, 0, 0
            cap_count = 1
        item_list = list(sub)
    if not item_list:
        return False, 0, 0
    for op, _av in item_list:
        name = str(op)
        if name not in _ALLOWED_OPCODES:
            raise error_cls(f"unsupported regex construct {name}")
        if name != "LITERAL":
            return False, 0, 0
    return True, len(item_list), cap_count


def _leading_spec(
    items: Iterable,
    flags: int,
    *,
    error_cls: type[Exception] = ValueError,
) -> Tuple[Optional[Tuple[Tuple[int, int], ...]], bool]:
    acc: List[Tuple[int, int]] = []
    for op, av in items:
        name = str(op)
        if name not in _ALLOWED_OPCODES:
            raise error_cls(f"unsupported regex construct {name}")
        if name == "AT":
            continue
        if name in ("LITERAL", "NOT_LITERAL", "IN", "ANY"):
            spec, _, _ = _atom_spec((op, av), flags, error_cls=error_cls)
            acc.extend(spec)
            return _merge_intervals(acc), False
        if name == "SUBPATTERN":
            _gid, add_f, del_f, sub = av
            sub_spec, sub_null = _leading_spec(sub, (flags | add_f) & ~del_f, error_cls=error_cls)
            if sub_spec is None:
                return None, True
            acc.extend(sub_spec)
            if not sub_null:
                return _merge_intervals(acc), False
            continue
        if name == "BRANCH":
            any_null = False
            for br in av[1]:
                br_spec, br_null = _leading_spec(br, flags, error_cls=error_cls)
                if br_spec is None:
                    return None, True
                acc.extend(br_spec)
                if br_null:
                    any_null = True
            if not any_null:
                return _merge_intervals(acc), False
            continue
        if name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
            rmin, _rmax, sub = av
            sub_spec, sub_null = _leading_spec(sub, flags, error_cls=error_cls)
            if sub_spec is None:
                return None, True
            acc.extend(sub_spec)
            if rmin >= 1 and not sub_null:
                return _merge_intervals(acc), False
            continue
        return None, True
    return (_merge_intervals(acc) if acc else ()), True


def _branches_pairwise_disjoint(
    branches: Sequence[Any],
    flags: int,
    *,
    error_cls: type[Exception] = ValueError,
) -> bool:
    seen: List[Tuple[Tuple[int, int], ...]] = []
    for br in branches:
        spec, nullable = _leading_spec(br, flags, error_cls=error_cls)
        if nullable or spec is None or not spec:
            return False
        if any(_intervals_overlap(prev, spec) for prev in seen):
            return False
        seen.append(spec)
    return True
