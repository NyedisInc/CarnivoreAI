#!/usr/bin/env python3
"""Build the public help pages: ``help/**/*.md`` (audience public) to static HTML.

Output goes to ``hosted/site/help/``: one ``index.html`` per page at its slug,
a generated index at ``/help/``, and ``help.css``. Pages whose front matter says
``audience: internal`` are skipped, and links to them are rendered as plain
text. The output is deterministic (no timestamps, sorted traversal) and
``--check`` fails when the committed output differs from a fresh build, the
same contract as ``scripts/web-build-check.sh``.

Usage:
    python3 scripts/help/build_site.py            # write hosted/site/help/
    python3 scripts/help/build_site.py --check    # exit 1 if the output is stale
    python3 scripts/help/build_site.py --out DIR  # write somewhere else

Exit: 0 ok, 1 stale (--check), 2 could not build (bad page, missing help/).
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.help.mdconv import render_inline, render_markdown  # noqa: E402
from scripts.help.pages import (  # noqa: E402
    AUDIENCE_PUBLIC, HELP_DIR_NAME, Page, PageError, load_pages,
)

SITE_HELP_URL = "/help/"
OUT_RELATIVE = Path("hosted") / "site" / "help"
SITE_ORIGIN = "https://carnivore.ai"
CSP = ("default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; "
       "base-uri 'none'; form-action 'none'")

HELP_CSS = """\
/* carnivore.ai help pages: layered on /legal.css (same palette, 2px corners, tracked capitals). no script. */
.crumbs { margin: 20px 0 0; font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase; color: var(--muted); }
.crumbs a { color: var(--muted); text-decoration: none; }
.crumbs a:hover, .crumbs a:focus-visible { color: var(--bright); }
.crumbs .sep { margin: 0 8px; opacity: 0.6; }
h3 { margin: 24px 0 6px; font-size: 12px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--bright); }
h4, h5, h6 { margin: 18px 0 6px; font-size: 12px; color: var(--bright); }
code { padding: 1px 5px; border: 1px solid var(--wire); border-radius: 2px; font-size: 12.5px; background: rgba(160, 168, 174, 0.06); word-break: break-word; }
pre { margin: 0 0 14px; padding: 12px 14px; overflow-x: auto; border: 1px solid var(--wire); border-radius: 2px; background: rgba(160, 168, 174, 0.06); }
pre code { padding: 0; border: 0; background: none; word-break: normal; }
.tbl { margin: 0 0 14px; overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 6px 10px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--wire); }
th { font-size: 11px; letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); }
.page-list { list-style: none; padding-left: 0; }
.page-list li { margin-bottom: 10px; }
.page-list .sub { padding-left: 22px; margin-top: 6px; list-style: none; }
.page-list .sub li { margin-bottom: 4px; }
"""


def page_href(slug: str) -> str:
    return f"{SITE_HELP_URL}{slug}/"


def make_resolver(page: Page, by_source: dict[str, Page]):
    src_dir = posixpath.dirname(page.rel)

    def resolve(target: str) -> str | None:
        if target.startswith(("http://", "https://")):
            return target
        if target.startswith("#"):
            return target
        path, _, frag = target.partition("#")
        if not path.endswith(".md"):
            return None
        dest = by_source.get(posixpath.normpath(posixpath.join(src_dir, path)))
        if dest is None or dest.audience != AUDIENCE_PUBLIC:
            return None
        return page_href(dest.slug) + (f"#{frag}" if frag else "")

    return resolve


def _first_paragraph(body: str) -> str:
    """Plain text of the first paragraph after the title, for the meta description."""
    for block in body.split("\n\n"):
        text = block.strip()
        if text and not text.startswith(("#", "|", "-", "```")):
            text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
            flat = " ".join(text.replace("*", "").replace("`", "").split())
            return flat[:157] + "..." if len(flat) > 160 else flat
    return ""


def shell(title: str, description: str, canonical: str, crumbs: str, main: str, updated: str) -> str:
    stamp = f'<p class="stamp">updated {html.escape(updated)}</p>\n' if updated else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>{html.escape(title)} - carnivore help</title>
<meta name="description" content="{html.escape(description, quote=True)}">
<link rel="canonical" href="{SITE_ORIGIN}{canonical}">
<meta name="theme-color" content="#02161e">
<meta name="color-scheme" content="dark">
<link rel="icon" type="image/png" sizes="192x192" href="/assets/icons/icon-192.png">
<link rel="stylesheet" href="/legal.css">
<link rel="stylesheet" href="{SITE_HELP_URL}help.css">
</head>
<body>
<div class="doc">
  <nav class="doc-bar" aria-label="carnivore.ai">
    <a href="/">carnivore</a>
    <a href="{SITE_HELP_URL}" class="here">help</a>
    <a href="/terms/2026-10-01/">terms</a>
    <a href="/privacy/">privacy</a>
  </nav>
{crumbs}  <main>
{main}
{stamp}  </main>
  <p class="doc-foot"><a href="/">carnivore.ai</a></p>
</div>
</body>
</html>
"""


def breadcrumb(page: Page | None, by_slug: dict[str, Page]) -> str:
    trail = [("carnivore", "/"), ("help", SITE_HELP_URL)]
    chain: list[Page] = []
    cur = page
    seen: set[str] = set()
    while cur is not None and cur.slug not in seen:
        seen.add(cur.slug)
        chain.append(cur)
        cur = by_slug.get(cur.parent) if cur.parent else None
    trail += [(p.title, page_href(p.slug)) for p in reversed(chain)]
    parts = []
    for i, (label, href) in enumerate(trail):
        last = i == len(trail) - 1
        cell = (f'<span aria-current="page">{html.escape(label)}</span>' if last
                else f'<a href="{href}">{html.escape(label)}</a>')
        parts.append(cell)
    sep = '<span class="sep">/</span>'
    return f'  <nav class="crumbs" aria-label="breadcrumb">{sep.join(parts)}</nav>\n'


def children_of(slug: str, pages: list[Page]) -> list[Page]:
    return sorted((p for p in pages if p.parent == slug), key=lambda p: (p.order, p.slug))


def render_page(page: Page, pages: list[Page], by_slug: dict[str, Page],
                by_source: dict[str, Page]) -> str:
    body = render_markdown(page.body, make_resolver(page, by_source))
    kids = children_of(page.slug, pages)
    if kids and not any(f'href="{page_href(k.slug)}' in body for k in kids):
        items = "\n".join(
            f'<li><a href="{page_href(k.slug)}">{html.escape(k.title)}</a></li>' for k in kids)
        body += f'\n<h2 id="sub-pages">Sub pages</h2>\n<ul>\n{items}\n</ul>'
    return shell(page.title, _first_paragraph(page.body), page_href(page.slug),
                 breadcrumb(page, by_slug), body, str(page.meta.get("updated") or ""))


def render_index(pages: list[Page], by_slug: dict[str, Page]) -> str:
    roots = sorted((p for p in pages if not p.parent or p.parent not in by_slug),
                   key=lambda p: (p.order, p.slug))
    rows = []
    for root in roots:
        subs = "\n".join(
            f'<li><a href="{page_href(k.slug)}">{html.escape(k.title)}</a></li>'
            for k in children_of(root.slug, pages))
        sub_html = f'\n<ul class="sub">\n{subs}\n</ul>\n' if subs else ""
        rows.append(f'<li><a href="{page_href(root.slug)}">{html.escape(root.title)}</a>{sub_html}</li>')
    main = ('<h1>Help</h1>\n<p class="stamp">detailed pages, one per feature</p>\n'
            '<ul class="page-list">\n' + "\n".join(rows) + "\n</ul>")
    return shell("Help", "detailed help pages for each carnivore feature.", SITE_HELP_URL,
                 breadcrumb(None, by_slug), main, "")


def build_files(repo_root: Path) -> dict[str, str]:
    all_pages = load_pages(repo_root)
    slugs = [p.slug for p in all_pages]
    if len(set(slugs)) != len(slugs):
        raise PageError("duplicate slug among help pages")
    public = [p for p in all_pages if p.audience == AUDIENCE_PUBLIC]
    by_slug = {p.slug: p for p in public}
    by_source = {p.rel: p for p in all_pages}
    files = {"help.css": HELP_CSS, "index.html": render_index(public, by_slug)}
    for p in public:
        files[f"{p.slug}/index.html"] = render_page(p, public, by_slug, by_source)
    return files


def read_tree(out_dir: Path) -> dict[str, str]:
    if not out_dir.is_dir():
        return {}
    return {p.relative_to(out_dir).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(out_dir.rglob("*")) if p.is_file()}


def write_tree(out_dir: Path, files: dict[str, str]) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    for rel, text in files.items():
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """CLI entry. Returns 0 ok, 1 stale under --check, 2 could not build."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the output is stale")
    ap.add_argument("--out", type=Path, default=None, help="output directory")
    ap.add_argument("--repo", type=Path, default=REPO_ROOT, help="repo root (tests)")
    args = ap.parse_args(argv)
    out_dir = args.out or (args.repo / OUT_RELATIVE)
    if not (args.repo / HELP_DIR_NAME).is_dir():
        print(f"build_site: no {HELP_DIR_NAME}/ folder under {args.repo}", file=sys.stderr)
        return 2
    try:
        files = build_files(args.repo)
    except (PageError, OSError) as exc:
        print(f"build_site: cannot build: {exc}", file=sys.stderr)
        return 2
    if args.check:
        have = read_tree(out_dir)
        stale = sorted(k for k in set(files) | set(have) if files.get(k) != have.get(k))
        for k in stale:
            print(f"stale: {k}")
        print(f"build_site: {'STALE' if stale else 'ok'} ({len(files)} files)")
        return 1 if stale else 0
    write_tree(out_dir, files)
    print(f"build_site: wrote {len(files)} files to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
