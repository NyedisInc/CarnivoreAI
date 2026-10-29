
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

HELP_DIR_NAME = "help"
AUDIENCE_PUBLIC = "public"
AUDIENCE_INTERNAL = "internal"
AUDIENCE_VALUES = (AUDIENCE_PUBLIC, AUDIENCE_INTERNAL)
REQUIRED_FIELDS = (
    "title", "slug", "parent", "order", "features", "sources", "verified_at", "updated",
)


class PageError(ValueError):
    pass


@dataclass(frozen=True)
class Page:

    path: Path
    meta: dict
    body: str
    audience: str = AUDIENCE_PUBLIC
    slug: str = ""
    parent: str | None = None
    order: int = 0
    title: str = ""
    features: tuple[str, ...] = field(default_factory=tuple)
    sources: tuple[str, ...] = field(default_factory=tuple)
    rel: str = ""


def _scalar(raw: str) -> object:
    text = raw.strip()
    if text in ("null", "~", ""):
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return int(text) if text.isdigit() else text


def parse_front_matter(text: str) -> tuple[dict, str]:
    """Split a page into (front matter dict, markdown body).

    Input: the whole file text. Output: the parsed fields and the body after
    the closing ``---``. Raises PageError when there is no front matter.
    Example: ``parse_front_matter('---\\na: 1\\n---\\n# T')`` is ``({'a': 1}, '# T')``.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise PageError("missing opening --- front matter fence")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise PageError("missing closing --- front matter fence") from None
    meta: dict = {}
    key: str | None = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if raw.lstrip().startswith("- ") and raw.startswith(" ") and key:
            meta[key].append(_scalar(raw.lstrip()[2:]))
            continue
        if ":" not in raw or raw.startswith(" "):
            raise PageError(f"cannot read front matter line: {raw!r}")
        name, _, value = raw.partition(":")
        key = name.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            meta[key] = [_scalar(p) for p in inner.split(",")] if inner else []
        elif value == "":
            meta[key] = []
        else:
            meta[key] = _scalar(value)
    return meta, "\n".join(lines[end + 1:]).lstrip("\n")


def load_page(path: Path, rel: str = "") -> Page:
    meta, body = parse_front_matter(path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_FIELDS if f not in meta]
    if missing:
        raise PageError(f"{path}: missing front matter fields {missing}")
    audience = meta.get("audience") or AUDIENCE_PUBLIC
    if audience not in AUDIENCE_VALUES:
        raise PageError(f"{path}: audience must be one of {AUDIENCE_VALUES}, got {audience!r}")
    order = meta["order"]
    if not isinstance(order, int):
        raise PageError(f"{path}: order must be an integer")
    return Page(
        path=path, meta=meta, body=body, audience=audience,
        slug=str(meta["slug"]), parent=meta["parent"], order=order,
        title=str(meta["title"]),
        features=tuple(str(f) for f in meta["features"]),
        sources=tuple(str(s) for s in meta["sources"]), rel=rel or path.as_posix(),
    )


def load_pages(repo_root: Path) -> list[Page]:
    base = repo_root / HELP_DIR_NAME
    files = sorted(p for p in base.rglob("*.md") if p.name != "README.md")
    return sorted((load_page(p, p.relative_to(repo_root).as_posix()) for p in files), key=lambda pg: pg.slug)
