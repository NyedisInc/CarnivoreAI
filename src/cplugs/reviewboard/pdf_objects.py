
from __future__ import annotations

from typing import Any, List, NamedTuple, Optional, Set, Union

from src.cplugs.reviewboard.pdf_lexer import REASON_SYNTAX, Lexer, Token
from src.cplugs.reviewboard.pdf_streams import PdfUnreadable

MAX_DEPTH = 64


class Name(str):
    pass


class Ref(NamedTuple):

    num: int
    gen: int


class Dict(dict):

    def __init__(self) -> None:
        super().__init__()
        self.dups: Set[str] = set()


Value = Union[None, bool, int, float, bytes, Name, Ref, "Dict", List[Any]]


def _ref_generation(lx: Lexer) -> Optional[int]:
    mark = lx.pos
    gen = lx.next()
    if gen is not None and gen[0] == "int":
        nxt = lx.next()
        if nxt is not None and nxt[0] == "kw" and nxt[1] == b"R":
            return int(gen[1])  # type: ignore[arg-type]
    lx.pos = mark
    return None


def parse_value(lx: Lexer, tok: Optional[Token] = None, depth: int = 0) -> Value:
    tok = tok or lx.next()
    if tok is None or depth > MAX_DEPTH:
        raise PdfUnreadable(REASON_SYNTAX)
    kind, value, _start = tok
    if kind == "name":
        return Name(str(value))
    if kind == "int":
        gen = _ref_generation(lx)
        return Ref(int(value), gen) if gen is not None else int(value)  # type: ignore[arg-type]
    if kind in ("real", "str"):
        return value  # type: ignore[return-value]
    if kind == "[":
        out: List[Any] = []
        while True:
            nxt = lx.next()
            if nxt is None:
                raise PdfUnreadable(REASON_SYNTAX)
            if nxt[0] == "]":
                return out
            out.append(parse_value(lx, nxt, depth + 1))
    if kind == "<<":
        return _parse_dict(lx, depth)
    if kind == "kw" and value in (b"true", b"false", b"null"):
        return None if value == b"null" else value == b"true"
    raise PdfUnreadable(REASON_SYNTAX)


def _parse_dict(lx: Lexer, depth: int) -> Dict:
    out = Dict()
    while True:
        key = lx.next()
        if key is None:
            raise PdfUnreadable(REASON_SYNTAX)
        if key[0] == ">>":
            return out
        if key[0] != "name":
            raise PdfUnreadable(REASON_SYNTAX)
        if key[1] in out:
            out.dups.add(str(key[1]))
        out[str(key[1])] = parse_value(lx, None, depth + 1)
