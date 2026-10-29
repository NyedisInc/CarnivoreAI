
from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.helpers.catalog_text import catalog_text

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO_ROOT / "client" / "js" / "i18n" / "catalog.en.js"

_CATALOG_ENTRY = re.compile(
    r"(?:'(?P<qkey>[A-Za-z0-9_.]+)'|(?P<bkey>zero|one|two|few|many|other))"
    r"\s*:\s*'(?P<value>(?:[^'\\]|\\.)*)'"
)

_BRITISH_SPELLINGS: tuple[tuple[str, str], ...] = (
    ("colour", "color"),
    ("colours", "colors"),
    ("coloured", "colored"),
    ("colouring", "coloring"),
    ("favour", "favor"),
    ("favours", "favors"),
    ("favoured", "favored"),
    ("favouring", "favoring"),
    ("favourite", "favorite"),
    ("favourites", "favorites"),
    ("behaviour", "behavior"),
    ("behaviours", "behaviors"),
    ("honour", "honor"),
    ("honours", "honors"),
    ("humour", "humor"),
    ("humours", "humors"),
    ("humoured", "humored"),
    ("labour", "labor"),
    ("labours", "labors"),
    ("laboured", "labored"),
    ("labouring", "laboring"),
    ("neighbour", "neighbor"),
    ("neighbours", "neighbors"),
    ("neighbouring", "neighboring"),
    ("rumour", "rumor"),
    ("rumours", "rumors"),
    ("armour", "armor"),
    ("armoured", "armored"),
    ("vapour", "vapor"),
    ("valour", "valor"),
    ("rigour", "rigor"),
    ("vigour", "vigor"),
    ("glamour", "glamor"),
    ("endeavour", "endeavor"),
    ("endeavours", "endeavors"),
    ("endeavoured", "endeavored"),
    ("endeavouring", "endeavoring"),
    ("savour", "savor"),
    ("savoury", "savory"),
    ("clamour", "clamor"),
    ("clamouring", "clamoring"),
    ("flavour", "flavor"),
    ("flavours", "flavors"),
    ("flavoured", "flavored"),
    ("flavouring", "flavoring"),
    ("ardour", "ardor"),
    ("odour", "odor"),
    ("odours", "odors"),
    ("tumour", "tumor"),
    ("tumours", "tumors"),
    ("harbour", "harbor"),
    ("harbours", "harbors"),
    ("parlour", "parlor"),
    ("splendour", "splendor"),
    ("organise", "organize"),
    ("organised", "organized"),
    ("organises", "organizes"),
    ("organising", "organizing"),
    ("organisation", "organization"),
    ("organisations", "organizations"),
    ("recognise", "recognize"),
    ("recognised", "recognized"),
    ("recognises", "recognizes"),
    ("recognising", "recognizing"),
    ("unrecognised", "unrecognized"),
    ("realise", "realize"),
    ("realised", "realized"),
    ("realises", "realizes"),
    ("realising", "realizing"),
    ("realisation", "realization"),
    ("apologise", "apologize"),
    ("apologised", "apologized"),
    ("apologises", "apologizes"),
    ("apologising", "apologizing"),
    ("analyse", "analyze"),
    ("analysed", "analyzed"),
    ("analysing", "analyzing"),
    ("customise", "customize"),
    ("customised", "customized"),
    ("customising", "customizing"),
    ("customisation", "customization"),
    ("optimise", "optimize"),
    ("optimised", "optimized"),
    ("optimising", "optimizing"),
    ("optimisation", "optimization"),
    ("minimise", "minimize"),
    ("minimised", "minimized"),
    ("minimising", "minimizing"),
    ("maximise", "maximize"),
    ("maximised", "maximized"),
    ("maximising", "maximizing"),
    ("finalise", "finalize"),
    ("finalised", "finalized"),
    ("finalising", "finalizing"),
    ("normalise", "normalize"),
    ("normalised", "normalized"),
    ("normalising", "normalizing"),
    ("serialise", "serialize"),
    ("serialised", "serialized"),
    ("serialising", "serializing"),
    ("specialise", "specialize"),
    ("specialised", "specialized"),
    ("specialising", "specializing"),
    ("prioritise", "prioritize"),
    ("prioritised", "prioritized"),
    ("prioritising", "prioritizing"),
    ("categorise", "categorize"),
    ("categorised", "categorized"),
    ("categorising", "categorizing"),
    ("utilise", "utilize"),
    ("utilised", "utilized"),
    ("utilising", "utilizing"),
    ("utilisation", "utilization"),
    ("synchronise", "synchronize"),
    ("synchronised", "synchronized"),
    ("synchronising", "synchronizing"),
    ("initialise", "initialize"),
    ("initialised", "initialized"),
    ("initialising", "initializing"),
    ("criticise", "criticize"),
    ("criticised", "criticized"),
    ("criticising", "criticizing"),
    ("emphasise", "emphasize"),
    ("emphasised", "emphasized"),
    ("emphasising", "emphasizing"),
    ("summarise", "summarize"),
    ("summarised", "summarized"),
    ("summarising", "summarizing"),
    ("capitalise", "capitalize"),
    ("capitalised", "capitalized"),
    ("capitalising", "capitalizing"),
    ("characterise", "characterize"),
    ("characterised", "characterized"),
    ("characterising", "characterizing"),
    ("generalise", "generalize"),
    ("generalised", "generalized"),
    ("generalising", "generalizing"),
    ("localise", "localize"),
    ("localised", "localized"),
    ("localising", "localizing"),
    ("memorise", "memorize"),
    ("memorised", "memorized"),
    ("memorising", "memorizing"),
    ("mobilise", "mobilize"),
    ("mobilised", "mobilized"),
    ("mobilising", "mobilizing"),
    ("modernise", "modernize"),
    ("modernised", "modernized"),
    ("modernising", "modernizing"),
    ("standardise", "standardize"),
    ("standardised", "standardized"),
    ("standardising", "standardizing"),
    ("stabilise", "stabilize"),
    ("stabilised", "stabilized"),
    ("stabilising", "stabilizing"),
    ("symbolise", "symbolize"),
    ("symbolised", "symbolized"),
    ("symbolising", "symbolizing"),
    ("sterilise", "sterilize"),
    ("sterilised", "sterilized"),
    ("sterilising", "sterilizing"),
    ("theorise", "theorize"),
    ("theorised", "theorized"),
    ("theorising", "theorizing"),
    ("visualise", "visualize"),
    ("visualised", "visualized"),
    ("visualising", "visualizing"),
    ("cancelled", "canceled"),
    ("cancelling", "canceling"),
    ("labelled", "labeled"),
    ("labelling", "labeling"),
    ("modelled", "modeled"),
    ("modelling", "modeling"),
    ("travelled", "traveled"),
    ("travelling", "traveling"),
    ("traveller", "traveler"),
    ("travellers", "travelers"),
    ("fuelled", "fueled"),
    ("fuelling", "fueling"),
    ("signalled", "signaled"),
    ("signalling", "signaling"),
    ("counsellor", "counselor"),
    ("counsellors", "counselors"),
    ("counselling", "counseling"),
    ("jewellery", "jewelry"),
    ("woollen", "woolen"),
    ("licence", "license"),
    ("licenced", "licensed"),
    ("licences", "licenses"),
    ("defence", "defense"),
    ("defences", "defenses"),
    ("offence", "offense"),
    ("offences", "offenses"),
    ("pretence", "pretense"),
    ("pretences", "pretenses"),
    ("practise", "practice"),
    ("practised", "practiced"),
    ("practising", "practicing"),
    ("cosy", "cozy"),
    ("cosier", "cozier"),
    ("cosiest", "coziest"),
    ("storey", "story"),
    ("storeys", "stories"),
    ("instalment", "installment"),
    ("instalments", "installments"),
    ("skilful", "skillful"),
    ("skilfully", "skillfully"),
    ("wilful", "willful"),
    ("wilfully", "willfully"),
    ("moustache", "mustache"),
    ("moustaches", "mustaches"),
    ("plough", "plow"),
    ("ploughed", "plowed"),
    ("ploughing", "plowing"),
    ("cheque", "check"),
    ("cheques", "checks"),
    ("sceptic", "skeptic"),
    ("sceptics", "skeptics"),
    ("sceptical", "skeptical"),
    ("kerb", "curb"),
    ("kerbs", "curbs"),
    ("tyre", "tire"),
    ("tyres", "tires"),
    ("aluminium", "aluminum"),
    ("mould", "mold"),
    ("moulded", "molded"),
    ("moulding", "molding"),
    ("moulds", "molds"),
    ("smoulder", "smolder"),
    ("smouldering", "smoldering"),
    ("manoeuvre", "maneuver"),
    ("manoeuvres", "maneuvers"),
    ("manoeuvring", "maneuvering"),
    ("encyclopaedia", "encyclopedia"),
    ("paediatric", "pediatric"),
    ("paediatrics", "pediatrics"),
    ("gynaecology", "gynecology"),
    ("haemoglobin", "hemoglobin"),
    ("oestrogen", "estrogen"),
    ("foetus", "fetus"),
    ("foetuses", "fetuses"),
    ("leukaemia", "leukemia"),
    ("artefact", "artifact"),
    ("artefacts", "artifacts"),
    ("enrol", "enroll"),
    ("enrolment", "enrollment"),
    ("enrolments", "enrollments"),
    ("fulfil", "fulfill"),
    ("fulfilment", "fulfillment"),
    ("fulfilments", "fulfillments"),
    ("grey", "gray"),
    ("greyed", "grayed"),
    ("greying", "graying"),
    ("greyscale", "grayscale"),
    ("centre", "center"),
    ("centres", "centers"),
    ("centred", "centered"),
    ("centring", "centering"),
    ("theatre", "theater"),
    ("theatres", "theaters"),
    ("litre", "liter"),
    ("litres", "liters"),
    ("metre", "meter"),
    ("metres", "meters"),
    ("fibre", "fiber"),
    ("fibres", "fibers"),
    ("calibre", "caliber"),
    ("calibres", "calibers"),
    ("dialogue", "dialog"),
    ("dialogues", "dialogs"),
    ("catalogue", "catalog"),
    ("catalogues", "catalogs"),
)

_BRITISH_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(r"\b" + re.escape(british) + r"\b", re.IGNORECASE), american)
    for british, american in _BRITISH_SPELLINGS
)


def _catalog_text() -> str:
    if not CATALOG_PATH.is_file():
        pytest.fail(f"missing {CATALOG_PATH}")
    return catalog_text()


def _catalog_values(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for m in _CATALOG_ENTRY.finditer(text):
        key = m.group("qkey") or m.group("bkey")
        out.append((key, m.group("value")))
    return out


def test_the_extractor_finds_a_realistic_number_of_values() -> None:
    values = _catalog_values(_catalog_text())
    assert len(values) > 800, (
        f"only extracted {len(values)} catalog values; the entry regex is "
        "probably broken, since this catalog has well over 1000 entries"
    )


def test_no_catalog_value_uses_british_spelling() -> None:
    violations: list[str] = []
    for key, value in _catalog_values(_catalog_text()):
        for pattern, american in _BRITISH_PATTERNS:
            hit = pattern.search(value)
            if hit:
                violations.append(
                    f"'{key}': found {hit.group()!r} in value {value!r} "
                    f"(use {american!r})"
                )
    assert violations == [], (
        "catalog value(s) use British spelling; this app is US English "
        "throughout (CLAUDE.md Voice, ruling 4 in docs/DECISIONS.md):\n"
        + "\n".join(violations)
    )


def test_the_detector_can_actually_fail() -> None:
    sample_values = [
        ("x.y", "colour"),
        ("x.y", "no colour"),
        ("x.y", "organised"),
        ("x.y", "unrecognised"),
        ("x.y", "recognises"),
    ]
    for key, value in sample_values:
        hits = [
            pattern.search(value)
            for pattern, _american in _BRITISH_PATTERNS
            if pattern.search(value)
        ]
        assert hits, f"no British-spelling pattern fired on {value!r} ({key})"

    for value in ("color", "no color", "organized", "unrecognized", "recognizes"):
        hits = [p for p, _a in _BRITISH_PATTERNS if p.search(value)]
        assert hits == [], f"US spelling {value!r} false-positived on {hits}"


def test_extractor_ignores_keys_and_comments() -> None:
    sample = (
        "    // a comment that says colour and organised and unrecognised\n"
        "    'theme.sheet.colours.heading': 'colors',\n"
        "    'sidebar.group.colour.menu': 'color',\n"
    )
    values = _catalog_values(sample)
    assert values == [
        ("theme.sheet.colours.heading", "colors"),
        ("sidebar.group.colour.menu", "color"),
    ], (
        "the extractor picked up the comment line or a key's own spelling "
        f"as if it were a value: {values}"
    )



_PROSE_GLOBS: tuple[str, ...] = (
    "CLAUDE.md",
    "AGENTS.md",
    ".claude/skills/**/*.md",
    ".claude/agents/*.md",
    ".claude/commands/*.md",
)

_INLINE_CODE = re.compile(r"`[^`]*`")
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
_CURLY_QUOTE = re.compile("\u201c[^\u201d\n]*\u201d")
_IDENTIFIER_CHARS = re.compile(r"[_/\\]|--|\.\w|[=<>@#]")


def _prose_files() -> list[Path]:
    found: set[Path] = set()
    for pattern in _PROSE_GLOBS:
        found.update(p for p in REPO_ROOT.glob(pattern) if p.is_file())
    return sorted(found)


def _exempt_spans(line: str, quote_open: bool) -> tuple[list[tuple[int, int]], bool]:
    spans: list[tuple[int, int]] = [m.span() for m in _INLINE_CODE.finditer(line)]
    masked = _INLINE_CODE.sub(lambda m: " " * len(m.group()), line)
    start: int | None = 0 if quote_open else None
    for m in re.finditer('"', masked):
        if start is None:
            start = m.start()
        else:
            spans.append((start, m.end()))
            start = None
    if start is not None:
        spans.append((start, len(line)))
    spans += [m.span() for m in _CURLY_QUOTE.finditer(line)]
    spans += [m.span() for m in _LINK_TARGET.finditer(line)]
    for m in re.finditer(r"\S+", line):
        core = m.group().rstrip(".,;:)!?*\"'").lstrip("(*_[\"'")
        if _IDENTIFIER_CHARS.search(core) or (core.startswith("-") and len(core) > 1):
            spans.append(m.span())
    return spans, start is not None


def _british_in_prose(text: str) -> Iterator[tuple[int, str, str]]:
    fence = False
    quote_open = False
    for number, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if not line.strip():
            quote_open = False
        if fence or line.lstrip().startswith((">", "#")):
            continue
        spans, quote_open = _exempt_spans(line, quote_open)
        for pattern, american in _BRITISH_PATTERNS:
            for hit in pattern.finditer(line):
                if not any(a <= hit.start() < b for a, b in spans):
                    yield number, hit.group(), american


def test_agent_instruction_prose_uses_us_spelling() -> None:
    files = _prose_files()
    assert len(files) >= 5, f"the prose guard found only {len(files)} files"
    violations = [
        f"{path.relative_to(REPO_ROOT)}:{number}: {word!r} (use {american!r})"
        for path in files
        for number, word, american in _british_in_prose(
            path.read_text(encoding="utf-8")
        )
    ]
    assert violations == [], (
        "agent instruction prose uses British spelling (docs/DECISIONS.md, "
        "US spelling in agent instruction prose):\n" + "\n".join(violations)
    )


def test_the_prose_guard_can_fail_and_honors_its_exemptions() -> None:
    flagged = list(_british_in_prose("the colour is organised here"))
    assert [w for _n, w, _a in flagged] == ["colour", "organised"]

    exempt = (
        "`colour` in code, the key theme.sheet.colours.heading, a path "
        "client/css/colour.css, --oc-colour, and \"owner said colour\".\n"
        "> a quoted colour line\n"
        "# A colour heading\n"
        "```\ncolour inside a fence\n```\n"
        'a quote that runs "across\nlines of colour" ends\n'
    )
    assert list(_british_in_prose(exempt)) == []
    assert list(_british_in_prose('a stray " quote\n\nthe colour\n'))
