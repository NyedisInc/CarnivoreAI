
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from ._pattern_safety_spec import (
    MAX_AT_ASSERTIONS,
    MAX_BRANCH_PATHS,
    MAX_CAPTURING_GROUPS,
    MAX_NON_BOUNDARY_ASSERTIONS,
    MAX_OPTIONALS,
    MAX_PATTERN_LEN,
    MAX_POST_D2_AT,
    MAX_POST_D2_ATOMS,
    MAX_POST_UNANCHORED_AT,
    MAX_POST_UNANCHORED_ATOMS,
    MAX_POST_UNANCHORED_PREFIX_LITERALS,
    MAX_REPEAT_BOUND,
    MAX_TOTAL_REPEATS,
    MAX_UNANCHORED_REPEATS,
    MAX_UNANCHORED_WHOLE_BOUND,
    _ALLOWED_AT_CODES,
    _ALLOWED_OPCODES,
    _NON_BOUNDARY_AT_CODES,
    _atom_spec,
    _atom_spec_detail,
    _branches_pairwise_disjoint,
    _contains_broad,
    _contains_linear_in,
    _ic_variants,
    _is_literal_only_optional,
    _is_space_category_atom,
    _specs_overlap,
    _unwrap_single_atom,
)

try:
    from re import _constants as _sre_constants  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover
    import sre_constants as _sre_constants  # type: ignore[no-redef]

__all__ = [
    "MAX_PATTERN_LEN",
    "_atom_spec",
    "_ic_variants",
    "validate_pattern_ast",
]


@dataclass(frozen=True)
class _WalkState:
    active: Tuple[Tuple[Optional[Tuple[Tuple[int, int], ...]], bool, int, bool, bool], ...] = ()
    anchored_start: bool = False
    consumed: bool = False
    require_end: bool = False
    branch_paths: int = 1
    ambiguous_bp: int = 1
    unanchored_repeats: int = 0
    path_opts: int = 0
    lit_run_chars: Tuple[int, ...] = ()
    has_distinct_prefix: bool = False
    post_d2_literals: int = 0
    post_d2_at: int = 0
    post_unanch_literals: int = 0
    post_unanch_at: int = 0
    captures_seen: int = 0


def _merge_states(states: Sequence[_WalkState], *, disjoint_branch: bool = False) -> _WalkState:
    if not states:
        return _WalkState(anchored_start=True)
    merged_active: List[Any] = []
    seen = set()
    for st in states:
        for item in st.active:
            if item not in seen:
                seen.add(item)
                merged_active.append(item)
    return _WalkState(
        active=tuple(merged_active),
        anchored_start=all(st.anchored_start for st in states),
        consumed=any(st.consumed for st in states),
        require_end=any(st.require_end for st in states),
        branch_paths=sum(st.branch_paths for st in states),
        ambiguous_bp=(
            max(st.ambiguous_bp for st in states)
            if disjoint_branch
            else sum(st.ambiguous_bp for st in states)
        ),
        unanchored_repeats=max(st.unanchored_repeats for st in states),
        path_opts=max(st.path_opts for st in states),
        lit_run_chars=(),
        has_distinct_prefix=all(st.has_distinct_prefix for st in states),
        post_d2_literals=max(st.post_d2_literals for st in states),
        post_d2_at=max(st.post_d2_at for st in states),
        post_unanch_literals=max(st.post_unanch_literals for st in states),
        post_unanch_at=max(st.post_unanch_at for st in states),
        captures_seen=max(st.captures_seen for st in states),
    )


def _apply_barrier(
    active: Tuple[Tuple[Optional[Tuple[Tuple[int, int], ...]], bool, int, bool, bool], ...],
    b_spec: Optional[Tuple[Tuple[int, int], ...]],
) -> Tuple[Tuple[Optional[Tuple[Tuple[int, int], ...]], bool, int, bool, bool], ...]:
    return tuple(
        (s, broad, d, sg, tainted)
        for s, broad, d, sg, tainted in active
        if d >= 2 or _specs_overlap(s, b_spec)
    )


def validate_pattern_ast(
    parsed: Any,
    pattern: str,
    *,
    whole_region: bool = False,
    error_cls: type[Exception] = ValueError,
) -> None:
    base_flags = getattr(getattr(parsed, "state", None), "flags", 0)
    stats = {"repeats": 0, "optionals": 0, "captures": 0, "at_assertions": 0, "non_boundary_at": 0}
    max_chain = 1 if whole_region else 2

    def _walk(
        items: Iterable,
        inside_repeat: bool,
        st: _WalkState,
        flags: int,
        wrap_captures: int = 0,
        in_branch_or_opt: bool = False,
    ) -> _WalkState:
        active = st.active
        anchored_start = st.anchored_start
        consumed = st.consumed
        require_end = st.require_end
        branch_paths = st.branch_paths
        ambiguous_bp = st.ambiguous_bp
        unanchored_repeats = st.unanchored_repeats
        path_opts = st.path_opts
        lit_run_chars = st.lit_run_chars
        has_distinct_prefix = st.has_distinct_prefix
        post_d2_literals = st.post_d2_literals
        post_d2_at = st.post_d2_at
        post_unanch_literals = st.post_unanch_literals
        post_unanch_at = st.post_unanch_at
        captures_seen = st.captures_seen

        def _snapshot() -> _WalkState:
            return _WalkState(
                active=active,
                anchored_start=anchored_start,
                consumed=consumed,
                require_end=require_end,
                branch_paths=branch_paths,
                ambiguous_bp=ambiguous_bp,
                unanchored_repeats=unanchored_repeats,
                path_opts=path_opts,
                lit_run_chars=lit_run_chars,
                has_distinct_prefix=has_distinct_prefix,
                post_d2_literals=post_d2_literals,
                post_d2_at=post_d2_at,
                post_unanch_literals=post_unanch_literals,
                post_unanch_at=post_unanch_at,
                captures_seen=captures_seen,
            )

        for op, av in items:
            name = str(op)
            if name not in _ALLOWED_OPCODES:
                raise error_cls(f"unsupported regex construct {name} in {pattern!r}")
            if require_end:
                raise error_cls(f"unanchored trailing pattern after repeat in {pattern!r}")
            if name == "AT":
                if inside_repeat:
                    raise error_cls(f"assertion inside repeat in {pattern!r}")
                at_name = str(av)
                if at_name not in _ALLOWED_AT_CODES:
                    raise error_cls(f"unsupported regex assertion {at_name} in {pattern!r}")
                stats["at_assertions"] += 1
                if stats["at_assertions"] > MAX_AT_ASSERTIONS:
                    raise error_cls(f"too many assertions (>{MAX_AT_ASSERTIONS}) in {pattern!r}")
                is_non_boundary = at_name in _NON_BOUNDARY_AT_CODES
                if is_non_boundary:
                    stats["non_boundary_at"] += 1
                    if stats["non_boundary_at"] > MAX_NON_BOUNDARY_ASSERTIONS:
                        raise error_cls(
                            f"too many non-boundary assertions (>{MAX_NON_BOUNDARY_ASSERTIONS}) in {pattern!r}"
                        )
                    if active or unanchored_repeats > 0:
                        raise error_cls(
                            f"non-boundary assertion after active or unanchored repeat in {pattern!r}"
                        )
                lit_run_chars = ()
                if any(d >= 2 for _, _, d, _, _ in active):
                    post_d2_at += 1
                    if post_d2_at > MAX_POST_D2_AT or (post_d2_literals + post_d2_at) > MAX_POST_D2_ATOMS:
                        raise error_cls(
                            f"excessive trailing assertions after overlapping repeats in {pattern!r}"
                        )
                if not anchored_start and active:
                    if has_distinct_prefix:
                        raise error_cls(f"assertion after unanchored repeat in {pattern!r}")
                    post_unanch_at += 1
                    if (
                        post_unanch_at > MAX_POST_UNANCHORED_AT
                        or (post_unanch_literals + post_unanch_at) > MAX_POST_UNANCHORED_ATOMS
                    ):
                        raise error_cls(
                            f"excessive trailing assertions after unanchored repeat in {pattern!r}"
                        )
                if not consumed:
                    if at_name == "AT_BEGINNING_STRING":
                        anchored_start = True
                    elif at_name == "AT_BEGINNING" and (not whole_region or not (flags & re.MULTILINE)):
                        anchored_start = True
                    elif at_name == "AT_BEGINNING_LINE" and not whole_region:
                        anchored_start = True
            elif name in ("LITERAL", "NOT_LITERAL", "IN", "ANY"):
                b_spec, _, _ = _atom_spec((op, av), flags, error_cls=error_cls)
                overlaps_active = any(_specs_overlap(s, b_spec) for s, _, _, _, _ in active)
                uni_ic = bool(flags & re.IGNORECASE) and not (flags & re.ASCII)
                lit_cost = (
                    2 if (name == "LITERAL" and uni_ic and (av > 127 or len(_ic_variants(av, False)) > 1)) else 1
                )
                if any(d >= 2 for _, _, d, _, _ in active):
                    if name != "LITERAL":
                        raise error_cls(f"non-literal after overlapping repeats in {pattern!r}")
                    post_d2_literals += lit_cost
                    if (post_d2_literals + post_d2_at) > MAX_POST_D2_ATOMS:
                        raise error_cls(f"excessive trailing atoms after overlapping repeats in {pattern!r}")
                if not anchored_start and active and name != "LITERAL" and overlaps_active:
                    raise error_cls(f"overlapping non-literal after unanchored repeat in {pattern!r}")
                active = _apply_barrier(active, b_spec)
                consumed = True
                if not anchored_start and unanchored_repeats > 0:
                    if not active:
                        has_distinct_prefix = False
                        post_unanch_literals = 0
                        post_unanch_at = 0
                    else:
                        post_unanch_literals += 1 if has_distinct_prefix else lit_cost
                        if has_distinct_prefix:
                            if post_unanch_literals > MAX_POST_UNANCHORED_PREFIX_LITERALS:
                                raise error_cls(f"excessive trailing literals after unanchored repeat in {pattern!r}")
                        elif (post_unanch_literals + post_unanch_at) > MAX_POST_UNANCHORED_ATOMS:
                            raise error_cls(f"excessive trailing atoms after unanchored repeat in {pattern!r}")
                if (
                    name == "LITERAL"
                    and not inside_repeat
                    and unanchored_repeats == 0
                    and stats["repeats"] == 0
                    and branch_paths == 1
                    and path_opts == 0
                    and stats["captures"] == 0
                    and stats["at_assertions"] == 0
                ):
                    canon = min(_ic_variants(av, bool(flags & re.ASCII))) if (flags & re.IGNORECASE) else av
                    lit_run_chars = lit_run_chars + (canon,)
                    if len(set(lit_run_chars)) >= 4:
                        has_distinct_prefix = True
                else:
                    lit_run_chars = ()
            elif name == "SUBPATTERN":
                _gid, add_f, del_f, sub = av
                is_capture = _gid is not None
                if is_capture:
                    stats["captures"] += 1
                    if stats["captures"] > MAX_CAPTURING_GROUPS:
                        raise error_cls(
                            f"too many capturing groups (>{MAX_CAPTURING_GROUPS}) in {pattern!r}"
                        )
                    if any(d >= 2 for _, _, d, _, _ in active):
                        raise error_cls(f"capturing group after overlapping repeats in {pattern!r}")
                    if not anchored_start and active:
                        raise error_cls(f"capturing group after unanchored repeat in {pattern!r}")
                if add_f or del_f or is_capture:
                    lit_run_chars = ()
                sub_flags = (flags | add_f) & ~del_f
                out = _walk(
                    sub,
                    inside_repeat,
                    _snapshot(),
                    sub_flags,
                    wrap_captures=wrap_captures + (1 if is_capture else 0),
                    in_branch_or_opt=in_branch_or_opt,
                )
                active = out.active
                anchored_start = out.anchored_start
                consumed = out.consumed
                require_end = out.require_end
                branch_paths = out.branch_paths
                ambiguous_bp = out.ambiguous_bp
                unanchored_repeats = out.unanchored_repeats
                path_opts = out.path_opts
                lit_run_chars = () if (add_f or del_f or is_capture) else out.lit_run_chars
                has_distinct_prefix = out.has_distinct_prefix
                post_d2_literals = out.post_d2_literals
                post_d2_at = out.post_d2_at
                post_unanch_literals = out.post_unanch_literals
                post_unanch_at = out.post_unanch_at
                captures_seen = out.captures_seen + (1 if is_capture else 0)
            elif name == "BRANCH":
                if inside_repeat:
                    raise error_cls(f"alternation inside repeat in {pattern!r}")
                multi_branch = len(av[1]) > 1
                if multi_branch:
                    if any(d >= 2 for _, _, d, _, _ in active):
                        raise error_cls(f"branching after overlapping repeats in {pattern!r}")
                    if not anchored_start and active:
                        raise error_cls(f"branching after unanchored repeat in {pattern!r}")
                    lit_run_chars = ()
                bp_limit = 2 if (not anchored_start and unanchored_repeats > 0) else MAX_BRANCH_PATHS
                total_bp = 0
                branch_states: List[_WalkState] = []
                cur_state = _snapshot()
                arm_in_branch = in_branch_or_opt or multi_branch
                for br in av[1]:
                    br_st = _walk(
                        br,
                        inside_repeat,
                        cur_state,
                        flags,
                        wrap_captures=wrap_captures,
                        in_branch_or_opt=arm_in_branch,
                    )
                    total_bp += br_st.branch_paths
                    if total_bp > bp_limit:
                        raise error_cls(f"excessive branching paths (>{bp_limit}) in {pattern!r}")
                    branch_states.append(br_st)
                disjoint = multi_branch and _branches_pairwise_disjoint(av[1], flags, error_cls=error_cls)
                out = _merge_states(branch_states, disjoint_branch=disjoint)
                active = out.active
                anchored_start = out.anchored_start
                consumed = out.consumed
                require_end = out.require_end
                branch_paths = out.branch_paths
                ambiguous_bp = out.ambiguous_bp
                unanchored_repeats = out.unanchored_repeats
                path_opts = out.path_opts
                lit_run_chars = out.lit_run_chars
                has_distinct_prefix = out.has_distinct_prefix
                post_d2_literals = out.post_d2_literals
                post_d2_at = out.post_d2_at
                post_unanch_literals = out.post_unanch_literals
                post_unanch_at = out.post_unanch_at
                captures_seen = out.captures_seen
                if not anchored_start and unanchored_repeats > 0:
                    if branch_paths > 2:
                        raise error_cls(f"excessive branching paths with unanchored repeat in {pattern!r}")
                    if path_opts > 1:
                        raise error_cls(f"excessive optionals with unanchored repeat in {pattern!r}")
            elif name in ("MAX_REPEAT", "MIN_REPEAT", "POSSESSIVE_REPEAT"):
                rmin, rmax, sub = av
                if rmin > MAX_REPEAT_BOUND or (rmax != _sre_constants.MAXREPEAT and rmax > MAX_REPEAT_BOUND):
                    raise error_cls(f"repeat bound exceeds {MAX_REPEAT_BOUND} in {pattern!r}")
                if inside_repeat:
                    raise error_cls("nested quantifier in %r" % pattern)
                if rmax == 0 or (rmin == 1 and rmax == 1):
                    raise error_cls(f"disallowed unit or zero quantifier {{{rmin}}} in {pattern!r}")
                is_multi = rmax == _sre_constants.MAXREPEAT or rmax > 1
                if is_multi:
                    stats["repeats"] += 1
                    if stats["repeats"] > MAX_TOTAL_REPEATS:
                        raise error_cls(f"too many repeats (>{MAX_TOTAL_REPEATS}) in {pattern!r}")
                    lit_run_chars = ()
                    caps_before = stats["captures"]
                    _walk(sub, True, _WalkState(), flags, wrap_captures=wrap_captures)
                    sub_captures = stats["captures"] - caps_before
                    atom, atom_flags = _unwrap_single_atom(sub, flags)
                    if atom is not None:
                        r_spec, r_broad, r_simple_pos, r_linear_in = _atom_spec_detail(
                            atom, atom_flags, error_cls=error_cls
                        )
                        case_invariant = (not (atom_flags & re.IGNORECASE)) or (
                            r_spec == _atom_spec(atom, atom_flags & ~re.IGNORECASE, error_cls=error_cls)[0]
                        )
                        simple_greedy = (name == "MAX_REPEAT") and r_simple_pos and case_invariant
                    else:
                        r_spec = None
                        r_broad = _contains_broad(sub, flags, error_cls=error_cls)
                        r_linear_in = _contains_linear_in(sub, flags, error_cls=error_cls)
                        simple_greedy = False

                    max_overlap_d = 0
                    any_d2 = False
                    overlap_broad = False
                    overlap_tainted = False
                    for s, broad, d, _sg, tainted in active:
                        if d >= 2:
                            any_d2 = True
                        if _specs_overlap(s, r_spec):
                            if d > max_overlap_d:
                                max_overlap_d = d
                            if broad:
                                overlap_broad = True
                            if tainted:
                                overlap_tainted = True

                    new_depth = 3 if any_d2 else (max_overlap_d + 1)
                    if new_depth > max_chain:
                        raise error_cls(f"coupled overlapping repeats in {pattern!r}")
                    if new_depth > 1 and (r_broad or overlap_broad):
                        raise error_cls(f"broad overlapping repeats in {pattern!r}")
                    if new_depth > 1 and not anchored_start:
                        raise error_cls(f"unanchored overlapping repeats in {pattern!r}")
                    if new_depth >= 2 and (ambiguous_bp > 1 or in_branch_or_opt or overlap_tainted):
                        raise error_cls(f"ambiguous branching paths with overlapping repeats in {pattern!r}")
                    if new_depth >= 2 and (wrap_captures + sub_captures > 0):
                        raise error_cls(f"capturing group with overlapping repeats in {pattern!r}")

                    if not anchored_start:
                        if ambiguous_bp > 1 or path_opts > 0 or in_branch_or_opt:
                            raise error_cls(f"ambiguous branching before unanchored repeat in {pattern!r}")
                        if r_linear_in:
                            raise error_cls(
                                f"broad linear character class in unanchored repeat in {pattern!r}"
                            )
                        if not has_distinct_prefix and r_broad and (atom is None or str(atom[0]) != "ANY"):
                            raise error_cls(f"broad unanchored repeat without distinct prefix in {pattern!r}")
                        if active and (
                            len(active) != 1
                            or not all(sg for _, _, _, sg, _ in active)
                            or rmin < 1
                            or not _is_space_category_atom(atom)
                        ):
                            raise error_cls(f"repeat after unanchored repeat in {pattern!r}")
                        unanchored_repeats += 1
                        if unanchored_repeats > MAX_UNANCHORED_REPEATS:
                            raise error_cls(
                                f"too many unanchored repeats (>{MAX_UNANCHORED_REPEATS}) in {pattern!r}"
                            )
                        if unanchored_repeats > 1:
                            has_distinct_prefix = False
                        if branch_paths > 2:
                            raise error_cls(f"excessive branching paths with unanchored repeat in {pattern!r}")
                        if path_opts > 1:
                            raise error_cls(f"excessive optionals with unanchored repeat in {pattern!r}")
                        if wrap_captures + captures_seen + sub_captures > 0:
                            if unanchored_repeats != 1 or has_distinct_prefix or stats["captures"] > 1:
                                raise error_cls(f"capturing group with unanchored repeat in {pattern!r}")
                            require_end = True

                    if rmin >= 1:
                        active = _apply_barrier(active, r_spec)
                        if not active and not anchored_start and unanchored_repeats > 0:
                            has_distinct_prefix = False
                            post_unanch_literals = 0
                            post_unanch_at = 0
                    active = (
                        *active,
                        (r_spec, r_broad, new_depth, simple_greedy, in_branch_or_opt or (wrap_captures + sub_captures > 0)),
                    )
                    consumed = True
                    captures_seen += sub_captures
                    if whole_region and not anchored_start and (
                        rmax == _sre_constants.MAXREPEAT or rmax > MAX_UNANCHORED_WHOLE_BOUND
                    ):
                        require_end = True
                else:
                    stats["optionals"] += 1
                    if stats["optionals"] > MAX_OPTIONALS:
                        raise error_cls(f"too many optionals (>{MAX_OPTIONALS}) in {pattern!r}")
                    if any(d >= 2 for _, _, d, _, _ in active):
                        raise error_cls(f"optional after overlapping repeats in {pattern!r}")
                    if not anchored_start and active:
                        if not has_distinct_prefix:
                            raise error_cls(f"optional after unanchored repeat in {pattern!r}")
                        if path_opts > 0:
                            raise error_cls(f"excessive optionals after unanchored repeat in {pattern!r}")
                        ok, lit_count, cap_count = _is_literal_only_optional(
                            sub, allow_one_capture=True, error_cls=error_cls
                        )
                        if not ok:
                            raise error_cls(f"complex optional after unanchored repeat in {pattern!r}")
                        if (post_unanch_literals + lit_count) > MAX_POST_UNANCHORED_PREFIX_LITERALS:
                            raise error_cls(
                                f"excessive trailing literals after unanchored repeat in {pattern!r}"
                            )
                        if (stats["captures"] + cap_count) > MAX_CAPTURING_GROUPS:
                            raise error_cls(
                                f"too many capturing groups (>{MAX_CAPTURING_GROUPS}) in {pattern!r}"
                            )
                        if (branch_paths + 1) > 2:
                            raise error_cls(
                                f"excessive branching paths with unanchored repeat in {pattern!r}"
                            )
                        stats["captures"] += cap_count
                        captures_seen += cap_count
                        path_opts += 1
                        post_unanch_literals += lit_count
                        branch_paths += 1
                        ambiguous_bp += 1
                        lit_run_chars = ()
                    else:
                        lit_run_chars = ()
                        path_opts += 1
                        bp_limit = 2 if (not anchored_start and unanchored_repeats > 0) else MAX_BRANCH_PATHS
                        cur_state = _snapshot()
                        skip_state = cur_state
                        take_state = _walk(
                            sub, inside_repeat, cur_state, flags, wrap_captures=wrap_captures, in_branch_or_opt=True
                        )
                        if skip_state.branch_paths + take_state.branch_paths > bp_limit:
                            raise error_cls(f"excessive branching paths (>{bp_limit}) in {pattern!r}")
                        out = _merge_states([skip_state, take_state], disjoint_branch=False)
                        active = out.active
                        anchored_start = out.anchored_start
                        consumed = out.consumed
                        require_end = out.require_end
                        branch_paths = out.branch_paths
                        ambiguous_bp = out.ambiguous_bp
                        unanchored_repeats = out.unanchored_repeats
                        path_opts = out.path_opts
                        lit_run_chars = out.lit_run_chars
                        has_distinct_prefix = out.has_distinct_prefix
                        post_d2_literals = out.post_d2_literals
                        post_d2_at = out.post_d2_at
                        post_unanch_literals = out.post_unanch_literals
                        post_unanch_at = out.post_unanch_at
                        captures_seen = out.captures_seen
                        if not anchored_start and unanchored_repeats > 0:
                            if branch_paths > 2:
                                raise error_cls(f"excessive branching paths with unanchored repeat in {pattern!r}")
                            if path_opts > 1:
                                raise error_cls(f"excessive optionals with unanchored repeat in {pattern!r}")
        return _snapshot()

    _walk(parsed, False, _WalkState(), base_flags)
