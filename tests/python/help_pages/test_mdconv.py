
from scripts.help.mdconv import render_inline, render_markdown, slugify


def _r(target: str):
    return target if target.startswith("http") else None


def test_headings_get_unique_ids():
    out = render_markdown("# A\n\n## Same\n\n## Same", _r)
    assert '<h1 id="a">A</h1>' in out
    assert 'id="same"' in out and 'id="same-1"' in out


def test_inline_escapes_html_and_formats():
    out = render_inline("**b** *i* `a<b | c` <script>", _r)
    assert "<strong>b</strong>" in out and "<em>i</em>" in out
    assert "<code>a&lt;b | c</code>" in out
    assert "&lt;script&gt;" in out and "<script>" not in out


def test_link_resolver_keeps_or_drops():
    assert 'href="https://x.y/z"' in render_inline("[go](https://x.y/z)", _r)
    dropped = render_inline("[go](other.md)", _r)
    assert "<a" not in dropped and "go" in dropped


def test_table_with_pipe_inside_code():
    md = "| a | b |\n|---|---|\n| `x|y` | two |\n"
    out = render_markdown(md, _r)
    assert "<th>a</th><th>b</th>" in out
    assert "<td><code>x|y</code></td><td>two</td>" in out


def test_nested_and_numbered_lists_with_continuation():
    md = "1. first\n   wraps here\n   - sub a\n   - sub b\n2. second\n"
    out = render_markdown(md, _r)
    assert out.count("<ol>") == 1 and out.count("<ul>") == 1
    assert "first wraps here" in out
    assert "<li>sub a</li>" in out and "<li>second</li>" in out


def test_fenced_code_is_escaped_and_verbatim():
    out = render_markdown("```\n<b>x</b>\n  y\n```", _r)
    assert "<pre><code>&lt;b&gt;x&lt;/b&gt;\n  y</code></pre>" in out


def test_paragraph_lines_join_and_deterministic():
    md = "one\ntwo\n\nthree"
    assert render_markdown(md, _r) == render_markdown(md, _r)
    assert "<p>one two</p>" in render_markdown(md, _r)


def test_slugify():
    assert slugify("For AI: key facts") == "for-ai-key-facts"
