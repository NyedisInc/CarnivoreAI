
from __future__ import annotations

import html.entities
import json
import random
import re
import subprocess
from pathlib import Path
from typing import List, Tuple

from markdown_it import MarkdownIt
from mdurl import parse as mdurl_parse

from src.plugins.host import ui_doc
from src.plugins.host.ui_doc_markdown import check_markdown_safe_violation

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LINK_CHECK = re.compile(r"^(?:[A-Za-z][A-Za-z0-9+.\-]*:|//)")


def _py_verdict(text: str) -> Tuple[bool, str | None]:
    try:
        ui_doc.validate({"schema": 2, "root": {"type": "markdown_safe", "value": text}}, routes=(), tools=())
        return True, None
    except ui_doc.UiDocError as exc:
        return False, exc.code


def _ts_verdicts(cases: List[str]) -> List[Tuple[bool, str | None]]:
    script = """
import fs from "node:fs";
import { createJiti } from "jiti";
const jiti = createJiti(import.meta.url);
const { validateDocument } = await jiti.import("./src/lib/cplug-ui/validate.ts");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
const out = cases.map((s) => {
  const v = validateDocument({ schema: 2, root: { type: "markdown_safe", value: s } }, { routes: [], tools: [] });
  return [v.ok, v.ok ? null : v.code];
});
process.stdout.write(JSON.stringify(out));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_REPO_ROOT / "web",
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        check=True,
    )
    return [(bool(ok), code) for ok, code in json.loads(proc.stdout)]


def _assert_parity_and_no_markdown_it_bypasses(cases: List[str]) -> None:
    md = MarkdownIt("commonmark", {"html": True})
    ts_results = _ts_verdicts(cases)
    assert len(ts_results) == len(cases)

    diffs: List[Tuple[str, Tuple[bool, str | None], Tuple[bool, str | None]]] = []
    bypasses: List[Tuple[str, str, str]] = []

    for payload, ts_verdict in zip(cases, ts_results):
        py_verdict = _py_verdict(payload)
        if py_verdict != ts_verdict:
            diffs.append((payload, py_verdict, ts_verdict))
        if py_verdict[0]:
            for tok in md.parse(payload):
                if tok.type in ("html_block", "html_inline"):
                    bypasses.append(("html_block", payload, tok.content))
                elif tok.children:
                    for ch in tok.children:
                        if ch.type == "html_inline":
                            bypasses.append(("html_inline", payload, ch.content))
                        elif ch.type in ("link_open", "image"):
                            attr = str(ch.attrs.get("href") or ch.attrs.get("src") or "")
                            parsed = mdurl_parse(attr)
                            if (parsed.protocol and _LINK_CHECK.match(parsed.protocol)) or attr.lstrip().startswith("//"):
                                bypasses.append(("url", payload, attr))

    assert diffs == [], f"Python/TS parity diffs (first 5): {diffs[:5]}"
    assert bypasses == [], f"markdown-it bypasses (first 5): {bypasses[:5]}"


def test_all_2125_html5_entities_python_ts_and_markdown_it_parity() -> None:
    entities = sorted(k[:-1] for k in html.entities.html5 if k.endswith(";"))
    assert len(entities) == 2125

    cases: List[str] = []
    for ent in entities:
        cases.append(f"x&{ent};http://evil.com")
        cases.append(f"[click](&{ent};https://evil.com)")
        cases.append(f"[click](&{ent};a:1)")
        cases.append(f"[click](javascrip&{ent};t:alert(1))")

    _assert_parity_and_no_markdown_it_bypasses(cases)


def test_differential_fuzzer_20000_commonmark_cases() -> None:
    rng = random.Random(20261124)
    tokens = [
        "`", "``", "```", "~~~", "\n", " ", "  ", "    ", "     ", "> ", "- ", "1. ", "2. ", "0. ",
        "10. ", "100. ", "1000. ", "\\", "\\`", "\\<", "\\:", "\\\n", "[", "]", "![", "](", "]]", "(", ")", "<", ">", '"', "'", "!", "#", "---", "===",
        "<script>", "</script>", "<img src=x>", "<?php echo 1", "<?php ?>", "<!DOCTYPE html",
        "<![CDATA[x", "<div", "<a + b>", '<span title="`">', "<a x=1\u00a0y =2>", "<a x=\u00a0\u00a0y =2>",
        "<a x=1\u00a0y\n=2>", "https://evil.com", "//evil.com", "javascript:alert(1)", "a:1", "12:30",
        "&emsp13;", "&emsp14;", "&ensp;", "&hairsp;", "&nbsp;", "&colon;", "&Tab;", "&NewLine;",
        "&#x0a;", "&#x0b;", "&#x3a;", "&#x5c;", "\u00a0", "\u2002", "\u3000", "foo", "bar", "x", "y", "=", "\n\n",
    ]
    lines_pool = [
        "", "  ", "   ", "    ", "     ", "      ", "> ", "> - ", "> 100. ", "> 1000. ",
        ">     ```", ">     <script>alert(1)</script>", "- ", "- - ", "- - - ", "1. ", "2. ", "10. ", "100. ", "1000. ",
        "100. foo", "1000. foo", "100. `foo", "> 100. foo", "> 100. `foo", "- - foo",
        "    ```", "    ~~~", "     ```", "    <div>", "    # <script>", "    ---", "    > <script>",
        "    <script>alert(1)</script>", "     <script>alert(1)</script>", "    [x](//evil.com)", "    [x](a:1)",
        "[a]:\\", "[a]: x\\", "[a]: x\\\n", "[a]: x\\\\", "[a]: <x\\", "[a]: //evil.com\\",
        "> [a]: x\\", "100. [a]: x\\", "[a]: a:1", "[a]:\n//evil.com", '[a]:\nhttps\\://evil.com\n"`"', "[a\nb]: &emsp13;a:1",
        "[click][a]", "[click][a\nb]", "![alt](&emsp14;a:1)", '[click](b "`")',
        '<span title="`">', '<a title=">">', "<?php", "<?php ?>", "<!DOCTYPE", "<![CDATA[", "<div",
        "<div\nonclick=1>", "<a x=1\u00a0y =2>", "a <a x=1\u00a0y =2>", "a <a x=\u00a0\u00a0y =2>",
        "[`<img src=x onerror=alert(1)>`a`", "![`<img src=x onerror=alert(1)>`a`", "[`<script>`] `", "[`<script>`](ok)",
        "`x`", "`` ` ``", "`", "```", "~~~", "---", "===", "# `", "## <script>", "<script>",
        "    <script>", '\\<div class="x">', "<a + b>",
        "[x](<//evil.com>)", "[x](\u00a0a:1)", "[x](&nbsp;a\\:1)", "<x@y.com>",
    ]

    cases: List[str] = [
        '[a](b "`") <script>alert(1)</script> `x`',
        '<span title="`"><script>alert(1)</script>`x`',
        "<?php echo 1",
        "<!DOCTYPE html",
        "<![CDATA[ alert(1)",
        "<div",
        "[click](&emsp13;https://evil.com)",
        "[click](&emsp14;a:1)",
        '\\<div class="x">',
        "<a + b>",
        "    <script>alert(1)</script>",
        "100. foo\n    ```\n<script>alert(1)</script>",
        "100. foo\n    ~~~\n<script>alert(1)</script>",
        "1000. foo\n     ```\n<script>alert(1)</script>",
        "100. foo\n    ```\n<img src=x onerror=alert(1)>",
        "100. foo\n    ```\n<?php echo 1",
        "100. foo\n    ```\n[x](//evil.com)",
        "100. foo\n    ```\n[x](a:1)",
        "> 100. foo\n>     ```\n> <script>alert(1)</script>",
        "100. `foo\n    ```\n<script>alert(1)</script>`",
        "100. `foo\n    <div>\n<script>alert(1)</script>`",
        "> 100. `foo\n>     ```\n> <script>alert(1)</script>`",
        "[" * 64 + "]" * 64,
        "[" * 500 + "]" * 500,
        "[" * 300 + "a" + "](" * 100 + "b)",
        "![" * 400 + "a" + "](" * 200,
        "[" * 1000,
        "[[" * 400 + "a](javascript:alert(1))" + "]]" * 200,
        "a <a x=\u00a0b>",
        "a <a x=\u00a0>",
        "<a x=\u00a0>",
        "<a x=\u00a0b>",
        "a <a x=1\u00a02>",
        "a <a x=\u00a0y=1>",
        "a <a x=\u00a0\u00a0y=1>",
        "a <!-- a ---> b",
        "a <!----> b",
        "[a]:\\",
        "[a]: x\\\n<script>alert(1)</script>",
        "[a]: x\\\n# <script>alert(1)</script>",
        "[a]: x\\\n> <script>alert(1)</script>",
        "[a]: x\\\n```\n```\n<script>alert(1)</script>",
        "> [a]: x\\\n> <script>alert(1)</script>",
        "100. [a]: x\\\n    <script>alert(1)</script>",
        "100. [a]: x\\\n     <script>alert(1)</script>",
        "[a]: x\\\n<div\nonclick=1>",
        "[a]: x\\\n\"`\"\n`<script>alert(1)</script>`\n\n[a]",
        "[a](//evil.com\\\ny)",
        "[a](<//evil.com\\\ny>)",
        "a <a x=1\u00a0y =2>",
        "<a x=1\u00a0y =2>",
        "a <a x=\u00a0\u00a0y =2>",
        "a <a x=1\u00a0y\n=2>",
        "a <a x=1\u00a0y ='2'>",
        'a <a x=1\u00a0y ="2">',
        "a <a x=1\u00a0y=2\u00a0z =3>",
        "a <a x=\u00a01\u00a0y =2>",
        "a <a x=1\u2002y =2>",
        "[`<img src=x onerror=alert(1)>`a`",
        "\\\\<)[`--->\n</a></divhttps:`\\\\`\u3000``",
        "![`<img src=x onerror=alert(1)>`a`",
        "[`<img src=x onerror=alert(1)>`a`](ok)",
        "[[`<script>`] `",
        "[`<img src=x onerror=alert(1)>`][unclosed `\n\n[a]: ok",
        "[`<script>alert(1)</script>`][ `\n\n[a]: ok",
        "![`<img src=x onerror=alert(1)>`][unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][`\n\n[a]: ok",
        "[`<img src=x>`][a `]\n\n[a]: ok",
        "[`<img src=x>`][[a] `\n\n[a]: ok",
        "[`<img src=x>`][`a` `\n\n[a]: ok",
        "[[`<img src=x>`]][`\n\n[a]: ok",
        "[`<img src=x>`](a c[`\n\n[a]: ok",
        "[`<img src=x>`][a `]\n\n[a `]: ok",
        "[`<script>`][a] `\n\n[a]: ok",
        "[ [a] `<img src=x>` ][`\n\n[a]: ok",
        "[`<script>`](ok) `",
        "[`<img src=x onerror=alert(1)>`][[a](x/]) unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](<x/]>) unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](<]> ) `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](<]>) `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][![a](x/]) unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][![a](<]>) `\n\n[a]: ok",
        "[`<script>alert(1)</script>`][[a](x/]) `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](x \"t]\") unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](b \"]\") `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](x 't]') unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](x (])) unclosed `\n\n[a]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](x (t])) unclosed `\n\n[a]: ok",
        "[`<img src=x>`][![a](x \"t]\") unclosed `\n\n[a]: ok",
        "![`<img src=x>`](a c[`\n\n[a]: ok",
        "![`<img src=x onerror=alert(1)>`](a c[`\n\n[a]: ok",
        "![`<img src=x>`](a c[a `]\n\n[a]: ok",
        "![`<script>alert(1)</script>`](<[`\n\n[a]: ok",
        "![`<script>alert(1)</script>`](<[unclosed `\n\n[a]: ok",
        "![ [b] `<img src=x>` ](a c[`\n\n[a]: ok",
        "![`<img src=x>`](<[ `\n\n[a]: ok",
        "![`<img src=x>`](<[a `\n\n[a]: ok",
        "![`<img src=x>`](x \"[ `\n\n[a]: ok",
        "![`<img src=x>`](([ `\n\n[a]: ok",
        "![ ![a](b) `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ ![a] `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ ![ [a](b) ](x) `<img src=x>` ](a c[`\n\n[a]: ok",
        "[ ![ [a](b) ](x) `<img src=x>` ](a c[`\n\n[a]: ok",
        "[`<img src=x>`][<javascript:`>]\n\n[<javascript:`>]: ok",
        "[`<img src=x onerror=alert(1)>`][[a](data:image/png;base64,x/]) `\n\n[a]: ok",
        "![ [a](b) `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ [a] `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ ![ [a](b) ] `<img src=x>` ](a c[`\n\n[a]: ok",
        "![ ![a](b c `<img src=x>` ](d e[`\n\n[a]: ok",
        "[`<img src=x>`][[ [a](b) ](x/]) `\n\n[a]: ok",
        "[`<img src=x>`][ [a][b](c/]) `\n\n[a]: ok\n[b]: ok",
        "[`<img src=x>`](   \n\n[a]: ok",
        "[a][" + "[b](x/]) " * 200 + "`\n\n[a]: ok",
        "[a][" + "[b](x [" * 240 + "]" * 240 + "\n\n[a]: ok",
        "[a][" + "[b](x [" * 260 + "`\n\n[a]: ok",
        "![a][" + "![b](x/]) " * 190 + "`\n\n[a]: ok",
        "[`<img src=x>` [top][ ![ ![a][ [b](c) ] ](([r](x/]) (`\n\n[top]: ok\n[r]: ok",
        "[`<img src=x>` [top][ [a](javascript:1 ([b](y/]) (`\n\n[top]: ok\n[b]: ok",
        "[`<img src=x>`](javascript:x [b] `<script>1</script>\n\n[b]: ok",
    ]
    ref_bt_pieces = [
        "[", "]", "![", "][", "](", "\\[", "\\]", "\\`", "`", "``", "```",
        "<img src=x>", "<script>", "</a>", "a", "b", " ", "\n", "[a]", "[b]",
        "(a c[", "(<a b>c[", '(\"`\"', "(ok)", "]]", "[[",
        "](x/])", "](<x/]>", '](x "t]")', "](x 't]')", "](x (]))", "](<[", "](([", '](x "[', "![a](b)", "[a](b)",
        "javascript:1", "(javascript:1 ([b]", "![a][ [b](c) ]",
        "\n\n[a]: ok", "\n\n[b]: ok", "\n\n[`a`]: ok", "\n\n[a `]: ok",
    ]
    for _ in range(10000):
        cases.append("".join(rng.choice(tokens) for _ in range(rng.randint(2, 10))))
    for _ in range(10000):
        cases.append("\n".join(rng.choice(lines_pool) for _ in range(rng.randint(1, 6))))
    for _ in range(11000):
        s = "".join(rng.choice(ref_bt_pieces) for _ in range(rng.randint(3, 14)))
        if "[a]: ok" not in s and "[`a`]: ok" not in s:
            s += "\n\n[a]: ok"
        cases.append(s)

    assert len(cases) >= 30000
    _assert_parity_and_no_markdown_it_bypasses(cases)

    tab_cases = [
        ("1000. foo\n\t```\n<script>alert(1)</script>", "html_not_allowed"),
        ("1000. foo\n\t```\n[x](//evil.com)", "link_not_allowed"),
        ("> 1000. foo\n> \t  ```\n> <script>alert(1)</script>", "html_not_allowed"),
        ("> 1000. foo\n> \t```\n> <script>alert(1)</script>", None),
    ]
    ts_tab_script = """
import fs from "node:fs";
import { createJiti } from "jiti";
const jiti = createJiti(import.meta.url);
const { checkMarkdownSafeViolation } = await jiti.import("./src/lib/cplug-ui/markdown-safe.ts");
const cases = JSON.parse(fs.readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(cases.map((s) => checkMarkdownSafeViolation(s))));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", ts_tab_script],
        cwd=_REPO_ROOT / "web",
        input=json.dumps([p for p, _ in tab_cases]),
        text=True,
        capture_output=True,
        check=True,
    )
    ts_tab_results = json.loads(proc.stdout)
    for (payload, expected), ts_res in zip(tab_cases, ts_tab_results):
        py_res = check_markdown_safe_violation(payload)
        assert py_res == expected, (payload, expected, py_res)
        assert py_res == ts_res, (payload, py_res, ts_res)
