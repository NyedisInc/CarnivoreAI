import re
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / "client" / "js" / "i18n" / "catalog.en.js"
SCAN_DIRS = ("web/src", "client", "src", "macOS", "tests", "scripts", "hosted")
SCAN_SUFFIXES = {".ts", ".svelte", ".js", ".mjs", ".py", ".html", ".json"}
THIS_FILE = Path(__file__).resolve()
KEY_LINE = re.compile(r"^\s{4}'([a-zA-Z0-9_][\w.\-]*)'\s*:", re.M)
VITE_OUT_DIR = re.compile(r"outDir\s*=\s*fileURLToPath\(\s*new URL\(\s*'([^']+)'", re.S)
PREFIX_HELPERS = re.compile(r"\b[A-Za-z_]\w*\(\s*['\"]([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)['\"]\s*,")
JS_TEMPLATE = re.compile(r"`([a-z0-9_][^`\n]*\$\{[^`\n]*)`")
PY_FSTRING = re.compile(r"""(?<!\w)f?(?:"([a-z0-9_][a-z0-9_.\-]*\.[^"\n]*\{[^"\n]*)"|'([a-z0-9_][a-z0-9_.\-]*\.[^'\n]*\{[^'\n]*)')""")
INTERPOLATION = re.compile(r"\$\{[^}]*\}|\{[^}]*\}")
BUILT_FAMILIES = (
    "settings.group.",
    "notify.type.",
    "notify.copy.",
    "features.page.deps.kind.",
    "keymap.action.",
    "keymap.category.",
    "keymap.item.",
    "keymap.group.",
    "ios.",
)
BUILT_INFIXES = (".option.",)
MIN_PLAUSIBLE_KEYS = 1000


def built_output_dirs(repo: Path = REPO) -> list[str]:
    out: list[str] = []
    for config in sorted((repo / "web").glob("vite*.config.ts")):
        for rel in VITE_OUT_DIR.findall(config.read_text(encoding="utf-8")):
            out.append((config.parent / rel).resolve().relative_to(repo).as_posix() + "/")
    return out


class CatalogParseError(ValueError):
    pass


ENTRY_SHAPED = re.compile(r"^\s+['\"][^'\"]+['\"]\s*:")


def catalog_keys(catalog: Path = CATALOG) -> list[str]:
    text = catalog.read_text(encoding="utf-8")
    unreadable = [n for n, line in enumerate(text.split("\n"), 1) if ENTRY_SHAPED.match(line) and not KEY_LINE.match(line)]
    if unreadable:
        raise CatalogParseError(f"catalog lines the key scan cannot read (it would skip them): {unreadable[:10]}")
    return KEY_LINE.findall(text)


@lru_cache(maxsize=2)
def code_blob(repo: Path = REPO) -> str:
    built = built_output_dirs(repo)
    parts: list[str] = []
    for top in SCAN_DIRS:
        for path in (repo / top).rglob("*"):
            text = str(path)
            if path.suffix not in SCAN_SUFFIXES or "node_modules" in text or "/dist/" in text:
                continue
            if path.name == "catalog.en.js" or path.resolve() == THIS_FILE:
                continue
            if path.relative_to(repo).as_posix().startswith(tuple(built)):
                continue
            try:
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
    return "\n".join(parts)


@lru_cache(maxsize=2)
def built_name_patterns(blob: str) -> dict[str, list[re.Pattern[str]]]:
    seen: set[str] = set()
    patterns: dict[str, list[re.Pattern[str]]] = {}
    for match in JS_TEMPLATE.findall(blob) + [a or b for a, b in PY_FSTRING.findall(blob)]:
        literal_head = INTERPOLATION.split(match)[0]
        if literal_head.count(".") < 1 or not re.fullmatch(r"[a-z0-9_.\-]+", literal_head):
            continue
        raw_pieces = INTERPOLATION.split(match)
        if len(raw_pieces) > 2 and len([w for w in re.split(r"[.\-]", "".join(raw_pieces)) if w]) < 2:
            continue
        pieces = [re.escape(piece) for piece in raw_pieces]
        source = ""
        for index, piece in enumerate(pieces):
            if index:
                source += r"[\w\-]+" if index == len(pieces) - 1 and piece == "" else r"[\w.\-]+"
            source += piece
        if source not in seen:
            seen.add(source)
            patterns.setdefault(literal_head.split(".")[0], []).append(re.compile(source))
    return patterns


@lru_cache(maxsize=2)
def resolve_constants(blob: str) -> str:
    consts: dict[str, set[str]] = {}
    for name, value in re.findall(r"""\b([A-Z_][A-Z0-9_]*)\s*(?::\s*str(?:ing)?\s*)?=\s*['"]([a-z][\w.\-]*\.?)['"]""", blob):
        consts.setdefault(name, set()).add(value)
    for _ in range(2):
        for name, target in re.findall(r"\b([A-Z_][A-Z0-9_]*)\s*=\s*(?:\w+\.)?([A-Z_][A-Z0-9_]*)\s*$", blob, re.M):
            if target in consts:
                consts.setdefault(name, set()).update(consts[target])
    extra = {
        f"'{value}{rest.replace(chr(39), '').replace(chr(34), '')}'"
        for name, rest in re.findall(r"\$?\{([\w.]+)\}((?:\$?\{[^}\n]*\}|[\w.\-])*)", blob)
        for value in consts.get(name.rsplit(".", 1)[-1], ())
    }
    return blob + "\n" + "\n".join(extra)


def unused_keys(keys: list[str], blob: str) -> list[str]:
    blob = resolve_constants(blob)
    tokens = set(re.findall(r"[A-Za-z0-9_][\w.\-]*[A-Za-z0-9_]", blob))
    key_set = set(keys)
    literals = set(re.findall(r"['\"`]([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)[._]?['\"`]", blob)) - key_set
    helper_prefixes = tuple(x + sep for x in literals if x.count(".") >= 2 for sep in (".", "_"))
    prefixes = {p for p in re.findall(r"[`'\"]([a-zA-Z0-9_][\w.\-]*\.)(?:['\"`]\s*\+)", blob) if p.count(".") >= 2}
    heads = set(re.findall(r"[`]([a-zA-Z0-9_][\w.\-]*[._\-])\$\{", blob))
    heads |= set(re.findall(r"""\bf["']([a-zA-Z0-9_][\w.\-]*[._\-])\{""", blob))
    heads |= set(re.findall(r"[`'\"]([a-zA-Z0-9_][\w.\-]*\.)\$\{", blob))
    prefixes |= {p + "." for p in PREFIX_HELPERS.findall(blob) if p not in key_set}
    templates = built_name_patterns(blob)
    heads_by_first: dict[str, list[str]] = {}
    for head in heads:
        heads_by_first.setdefault(head.split(".")[0], []).append(head)
    dead: list[str] = []
    for key in keys:
        if key in tokens or key.startswith(BUILT_FAMILIES) or any(i in key for i in BUILT_INFIXES) or key.startswith(tuple(prefixes)) or key.startswith(helper_prefixes):
            continue
        first = key.split(".")[0]
        best = max((h for h in heads_by_first.get(first, ()) if key.startswith(h)), key=len, default="")
        if best.count(".") >= 2 and key[len(best):].count(".") <= 1:
            continue
        if any(t.fullmatch(key) for t in templates.get(first, ())):
            continue
        dead.append(key)
    return dead


def test_positive_control_the_scan_sees_the_catalog_and_the_code() -> None:
    assert len(catalog_keys()) > MIN_PLAUSIBLE_KEYS, "the key scan found almost nothing, so the check below would be vacuous"
    assert len(code_blob()) > 1_000_000, "the code scan found almost nothing, so every key would look unused"


def test_built_output_is_not_read_as_code() -> None:
    dirs = built_output_dirs()
    assert "hosted/catalog_index/site/browse/" in dirs and "client/dist/" in dirs, f"vite output folders not found: {dirs}"


def test_the_scan_can_go_red_on_an_unused_key() -> None:
    assert unused_keys(["zz.never.named.anywhere"], code_blob()) == ["zz.never.named.anywhere"]


def test_a_missing_catalog_fails_instead_of_passing() -> None:
    try:
        catalog_keys(REPO / "client" / "js" / "i18n" / "no-such-catalog.js")
    except FileNotFoundError:
        return
    raise AssertionError("a missing catalog read as an empty one, which would make the ratchet pass on nothing")


def test_no_catalog_key_is_unused() -> None:
    dead = unused_keys(catalog_keys(), code_blob())
    assert not dead, f"{len(dead)} catalog keys no code names (delete them, or register a built family): {dead}"


def test_a_template_fill_spans_several_segments() -> None:
    blob = 'subject = catalog_copy(f"mail.{template}.subject")\nlabel = `viz.${kind}`'
    keys = ["mail.admin.report.subject", "mail.admin.report.body", "viz.timeline", "viz.a.b"]
    assert unused_keys(keys, blob) == ["mail.admin.report.body", "viz.a.b"]


def test_a_planted_unused_key_still_fails_next_to_real_ones() -> None:
    assert unused_keys(catalog_keys() + ["zz.never.named.anywhere"], code_blob())[-1] == "zz.never.named.anywhere"


def test_an_unreadable_catalog_line_fails_loudly(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.en.js"
    catalog.write_text("    'a.b': 'x',\n    'Bad Key!': 'y',\n", encoding="utf-8")
    try:
        catalog_keys(catalog)
    except CatalogParseError:
        return
    raise AssertionError("an entry line the scan cannot parse was skipped silently")
