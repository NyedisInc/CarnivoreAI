
from __future__ import annotations

import base64
import json
import random
import string
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from src.core.message_model_secrets import (
    DETECTOR_ANTHROPIC_API_KEY,
    DETECTOR_CARNIVORE_API_KEY,
    DETECTOR_AWS_ACCESS_KEY_ID,
    DETECTOR_AWS_SECRET_ACCESS_KEY,
    DETECTOR_CLOUDFLARE_API_TOKEN,
    DETECTOR_GITHUB_TOKEN,
    DETECTOR_GOOGLE_API_KEY,
    DETECTOR_MINISIGN_SECRET_KEY,
    DETECTOR_OP_SERVICE_ACCOUNT,
    DETECTOR_OPENAI_API_KEY,
    DETECTOR_PEM_PRIVATE_KEY,
    DETECTOR_SLACK_TOKEN,
    VENDOR_DETECTORS,
)
from src.core.stream_redactor import StreamRedactor

LEAK_RUN: int = 12

_B62 = string.ascii_letters + string.digits
_B64 = _B62 + "+/"
_URLSAFE = _B62 + "-_"

Cell = Tuple[str, int, bool]


@dataclass
class Case:

    detector: str
    cells: List[Cell]
    chunks: List[str] = field(default_factory=list)
    flush_after: frozenset = frozenset()
    secret_len: int = 0
    shape: str = ""

    @property
    def stream(self) -> str:
        return "".join(cell[0] for cell in self.cells)


def _pick(rng: random.Random, alphabet: str, count: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(count))


def _secret(text: str) -> List[Cell]:
    return [(char, 0, False) for char in text]


def _public(text: str) -> List[Cell]:
    return [(char, -1, False) for char in text]


def _key_cells(detector: str, rng: random.Random) -> List[Cell]:
    if detector == DETECTOR_OP_SERVICE_ACCOUNT:
        body = base64.b64encode(rng.randbytes(rng.randint(45, 300))).decode()
        return _public("op" + "s_") + _secret(body)
    if detector == DETECTOR_GITHUB_TOKEN:
        if rng.random() < 0.25:
            return _public("github" + "_pat_") + _secret(
                _pick(rng, _B62, 22) + "_" + _pick(rng, _B62, 59))
        return _public("gh" + rng.choice("pousr") + "_") + _secret(_pick(rng, _B62, 36))
    if detector == DETECTOR_AWS_ACCESS_KEY_ID:
        prefix = rng.choice(["AK" + "IA", "AS" + "IA", "AR" + "OA", "AI" + "DA"])
        return _public(prefix) + _secret(_pick(rng, string.ascii_uppercase + string.digits, 16))
    if detector == DETECTOR_AWS_SECRET_ACCESS_KEY:
        name = rng.choice(["aws_secret_access_key", "AWS_SECRET_ACCESS_KEY",
                           "aws.secretAccessKey"])
        sep = rng.choice(["=", " = ", ": ", '": "', "='"])
        return _public(name + sep) + _secret(_pick(rng, _B64, 40))
    if detector == DETECTOR_GOOGLE_API_KEY:
        return _public("AI" + "za") + _secret(_pick(rng, _URLSAFE, 35))
    if detector == DETECTOR_SLACK_TOKEN:
        body = "-".join((_pick(rng, string.digits, rng.randint(10, 13)),
                         _pick(rng, string.digits, rng.randint(10, 13)),
                         _pick(rng, _B62, 24)))
        return _public("xo" + "x" + rng.choice("abprs") + "-") + _secret(body)
    if detector == DETECTOR_PEM_PRIVATE_KEY:
        label = rng.choice(["RSA ", "EC ", "OPENSSH ", "", "ENCRYPTED "])
        body = base64.b64encode(rng.randbytes(rng.randint(120, 600))).decode()
        lines = [body[i:i + 64] for i in range(0, len(body), 64)]
        cells = _public("-----BEG" + "IN " + label + "PRIVATE KEY-----\n")
        for line in lines:
            cells += _secret(line) + _public("\n")
        return cells + _public("-----END " + label + "PRIVATE KEY-----")
    if detector == DETECTOR_CLOUDFLARE_API_TOKEN:
        name = rng.choice(["CLOUDFLARE_API_TOKEN", "cf_api_token", "cloudflare.token"])
        return _public(name + rng.choice(["=", ": ", " = "])) + _secret(_pick(rng, _URLSAFE, 40))
    if detector == DETECTOR_MINISIGN_SECRET_KEY:
        body = base64.b64encode(rng.randbytes(158)).decode()
        return _public("untrusted comment: mini" + "sign encrypted secret key\n") + _secret(body)
    if detector == DETECTOR_ANTHROPIC_API_KEY:
        marker = rng.choice(["api03", "admin01", "oat01", "ort01"])
        return _public("sk-" + "ant-" + marker + "-") + _secret(_pick(rng, _URLSAFE, 93) + "AA")
    if detector == DETECTOR_OPENAI_API_KEY:
        marker = rng.choice(["proj", "svcacct", "admin"])
        return _public("sk-" + marker + "-") + _secret(
            _pick(rng, _URLSAFE, 74) + "T3Blbk" + "FJ" + _pick(rng, _URLSAFE, 74))
    if detector == DETECTOR_CARNIVORE_API_KEY:
        return _public("ca" + "k_") + _secret(_pick(rng, _URLSAFE, 41) + "Q7")
    raise ValueError(f"no generator for {detector}")


_WORDS = ("token", "here", "is", "key", "the", "new", "value", "done", "then",
          "restart", "export", "deploy", "saved", "vault", "creds", "OK", "id",
          "x", "3", "path/to", "err", "a")

_ESCAPE_SPELLINGS = ("", "\\n", "\\t", "\\r", "\\u001b[32m", "\\u001b[1;32m",
                     "\\x1b[32m", "\\u0027", "\\u003d", "\\u000a", '\\"', '"',
                     "'", "=", ":")

_CONTEXTUAL = (DETECTOR_AWS_SECRET_ACCESS_KEY, DETECTOR_CLOUDFLARE_API_TOKEN)
_ESCAPE_SPELLINGS_BEFORE_A_NAME = tuple(
    e for e in _ESCAPE_SPELLINGS if e not in ("=", ":", "\\u003d"))

_PREFIXES: Tuple[Callable[[int], str], ...] = (
    lambda n: "",
    lambda n: "  ",
    lambda n: "     ",
    lambda n: "\t",
    lambda n: "  ",
    lambda n: "| ",
    lambda n: "> ",
    lambda n: "> > ",
    lambda n: "+ ",
    lambda n: "- ",
    lambda n: "* ",
    lambda n: "+",
    lambda n: f"{n:>4} │ ",
    lambda n: f"{n}: ",
    lambda n: "     │ ",
)

_SEPARATORS = ("\n", "\r\n", "\r\r\n")

_GLYPHS = [chr(code) for code in range(0x2500, 0x25A0)]


def _prefix(rng: random.Random) -> Callable[[int], str]:
    if rng.random() < 0.3:
        glyph = rng.choice(_GLYPHS)
        pad = rng.choice(["", " ", "  "])
        return lambda n: glyph + pad
    return rng.choice(_PREFIXES)


def _sgr(rng: random.Random) -> str:
    return "\x1b[" + rng.choice(["0", "1", "2", "32", "1;32", "38;5;208", "39"]) + "m"


def _json_cells(cells: List[Cell]) -> List[Cell]:
    out: List[Cell] = []
    for char, tag, _escape in cells:
        spelled = json.dumps(char, ensure_ascii=False)[1:-1]
        if len(spelled) == 1:
            out.append((spelled, tag, False))
        else:
            out.extend((part, -1, False) for part in spelled)
    return out


def _wrap(
    cells: List[Cell], rng: random.Random, width: int,
    prefix: Callable[[int], str], first: str, sep: str, border: str,
) -> List[Cell]:
    out: List[Cell] = [(char, -1, False) for char in first]
    column = 0
    row = 1
    for index, (char, tag, escape) in enumerate(cells):
        if char == "\n" and not escape:
            out.extend((c, -1, True) for c in sep)
            out.extend((c, -1, False) for c in prefix(row))
            row += 1
            column = 0
            continue
        if not escape and column >= width:
            out.extend((c, -1, False) for c in border)
            out.extend((c, -1, True) for c in sep)
            out.extend((c, -1, False) for c in prefix(row))
            row += 1
            column = 0
        out.append((char, tag, escape))
        if not escape:
            column += 1
    return out


def make_case(rng: random.Random, detector: str) -> Case:
    key = _key_cells(detector, rng)
    shape: List[str] = []
    before = _public(rng.choice(_WORDS)) if rng.random() < 0.7 else []
    if before and rng.random() < 0.5:
        before += _public(" ")
        shape.append("spaced-head")
    escape = rng.choice(_ESCAPE_SPELLINGS if detector not in _CONTEXTUAL
                        else _ESCAPE_SPELLINGS_BEFORE_A_NAME)
    after = _public(rng.choice(_WORDS)) if rng.random() < 0.7 else []
    if after and rng.random() < 0.5:
        after = _public(rng.choice([" ", ",", ".", "\""])) + after
    line = _public(" ".join(rng.choice(_WORDS) for _ in range(rng.randint(0, 6))) + " ")
    line += before + _public(escape) + key + after
    shape.append(f"escape={escape!r}")

    as_json = rng.random() < 0.3
    if rng.random() < 0.5:
        key_at = len(line) - len(after) - len(key)
        spots = [rng.randint(0, len(line)) for _ in range(rng.randint(1, 4))]
        if as_json:
            spots = [at if not key_at < at < key_at + len(key)
                     else rng.choice([key_at, key_at + len(key)]) for at in spots]
        for at in sorted(spots, reverse=True):
            line[at:at] = [(c, -1, True) for c in _sgr(rng)]
        shape.append("sgr")
    if as_json:
        line = _public('{"type":"text","text":"') + _json_cells(line) + _public('"}')
        shape.append("json")

    width = rng.randint(20, 200)
    prefix = _prefix(rng)
    first = rng.choice(["", "⏺ ", "  ", "│ ", "$ "])
    border = rng.choice(["", "", " │", " ░", "  "])
    sep = rng.choice(_SEPARATORS)
    cells = _wrap(line, rng, width, prefix, first, sep, border)
    cells += [(c, -1, True) for c in sep]
    shape.append(f"width={width} prefix={prefix(7)!r} sep={sep!r} border={border!r}")

    numbered: List[Cell] = []
    count = 0
    for char, tag, escape in cells:
        if tag >= 0:
            numbered.append((char, count, escape))
            count += 1
        else:
            numbered.append((char, -1, escape))
    case = Case(detector, numbered, secret_len=count, shape=" ".join(shape))

    stream = case.stream
    cuts = sorted(rng.sample(range(1, len(stream)), k=min(len(stream) - 1, rng.randint(0, 12))))
    bounds = [0] + cuts + [len(stream)]
    case.chunks = [stream[a:b] for a, b in zip(bounds, bounds[1:])]
    case.flush_after = frozenset(
        i for i in range(len(case.chunks)) if rng.random() < 0.3)
    return case


def run_case(case: Case) -> str:
    redactor = StreamRedactor()
    out: List[str] = []
    for index, chunk in enumerate(case.chunks):
        out.append(redactor.feed(chunk))
        if index in case.flush_after:
            out.append(redactor.flush())
    out.append(redactor.flush(end=True))
    return "".join(out)


def check_case(case: Case, out: str) -> List[str]:
    stream = case.stream
    problems: List[str] = []
    if len(out) != len(stream):
        return [f"length {len(out)} != {len(stream)}"]
    visible = [False] * case.secret_len
    for position, (char, tag, escape) in enumerate(case.cells):
        if escape and out[position] != char:
            problems.append(f"escape or break byte changed at {position}")
            break
        if tag >= 0:
            visible[tag] = out[position] == char
    run = longest = 0
    for shown in visible:
        run = run + 1 if shown else 0
        longest = max(longest, run)
    if longest >= LEAK_RUN:
        problems.append(f"{longest} consecutive secret characters readable")
    return problems


def generate(seed: int, per_detector: int) -> List[Case]:
    rng = random.Random(seed)
    return [make_case(rng, detector)
            for _ in range(per_detector) for detector in VENDOR_DETECTORS]


def with_history(rng: random.Random, case: Case, tail: int) -> Case:
    cells: List[Cell] = []
    target = rng.randint(tail + 1, tail * 5)
    while len(cells) < target:
        roll = rng.random()
        if roll < 0.4:
            run = "".join(rng.choice([
                _sgr(rng), "\x1b[2K", "\x1b[1A", "\x1b[G",
                f"\x1b[{rng.randint(1, 50)};{rng.randint(1, 120)}H",
                "\x1b]0;" + rng.choice(_WORDS) + "\x07",
            ]) for _ in range(rng.randint(1, 8)))
            cells += [(c, -1, True) for c in run]
        else:
            cells += _public(" ".join(rng.choice(_WORDS)
                                      for _ in range(rng.randint(1, 12))))
            cells += [(c, -1, True) for c in "\r\n"]
    out = Case(case.detector, cells + case.cells, secret_len=case.secret_len,
               shape="history " + case.shape)
    stream = out.stream
    cuts = sorted(rng.sample(range(1, len(stream)), k=rng.randint(0, 40)))
    bounds = [0] + cuts + [len(stream)]
    out.chunks = [stream[a:b] for a, b in zip(bounds, bounds[1:])]
    out.flush_after = frozenset(
        i for i in range(len(out.chunks)) if rng.random() < 0.2)
    return out




def negative_corpus(rng: random.Random, sources: Dict[str, str]) -> List[str]:
    keyed = list(sources.items())
    docs = [doc for _, doc in keyed]
    for _ in range(40):
        docs.append("\n".join(
            f"2026-09-22T17:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d}Z "
            f"{rng.choice(['INFO', 'WARN', 'DEBUG'])} "
            f"request_id={rng.getrandbits(128):032x} path=/api/v1/"
            f"{rng.choice(['sessions', 'themes', 'links'])} took={rng.random():.3f}s"
            for _ in range(20)))
        docs.append("\n".join(
            f"{rng.choice('+- ')}    {rng.choice(_WORDS)} = "
            f"{rng.choice(_WORDS)}({rng.getrandbits(160):040x})" for _ in range(30)))
        docs.append("data:image/png;base64," + base64.b64encode(
            rng.randbytes(rng.randint(200, 3000))).decode())
        docs.append("\n".join(
            f"commit {rng.getrandbits(160):040x}\n{rng.getrandbits(128):032x}"
            f" {rng.getrandbits(32):08x}-{rng.getrandbits(16):04x}-4"
            f"{rng.getrandbits(12):03x}-a{rng.getrandbits(12):03x}-"
            f"{rng.getrandbits(48):012x}" for _ in range(15)))
    keys = [name for name, _ in keyed] + [f"generated-{i}" for i in range(len(docs) - len(keyed))]
    layout_seed = rng.getrandbits(64)
    streams = []
    for key, doc in zip(keys, docs):
        doc_rng = random.Random(f"{layout_seed}:{key}")
        width = doc_rng.randint(20, 200)
        prefix = _prefix(doc_rng)
        rows: List[str] = []
        for number, line in enumerate(doc.split("\n")):
            pieces = [line[i:i + width] for i in range(0, len(line), width)] or [""]
            rows.append(pieces[0])
            rows.extend(prefix(number) + piece for piece in pieces[1:])
        streams.append("\r\n".join(rows) + "\r\n")
    return streams


def overstar(stream: str) -> Tuple[int, int, int]:
    redactor = StreamRedactor()
    out = redactor.feed(stream) + redactor.flush(end=True)
    assert len(out) == len(stream)
    starred = sum(1 for a, b in zip(stream, out) if a != b)
    whole = 0
    for raw_row, out_row in zip(stream.split("\n"), out.split("\n")):
        text = [i for i, c in enumerate(raw_row) if not c.isspace()]
        if len(text) >= 16 and all(out_row[i] == "*" != raw_row[i] for i in text):
            whole += 1
    return starred, len(stream), whole
