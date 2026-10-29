
import subprocess
from pathlib import Path

PAGE = """---
title: {title}
slug: {slug}
parent: {parent}
order: {order}
features: [{features}]
{audience}sources:
{sources}verified_at: {sha}
updated: 2026-10-11
---

# {title}

{body}
"""


def git(repo: Path, *args: str) -> str:
    cmd = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


def write_page(repo: Path, rel: str, *, title="T", slug="a", parent="null", order=1,
               features="feat", audience="", sources=("src/a.py",), sha="HEAD", body="Body."):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    src = "".join(f"  - {s}\n" for s in sources)
    aud = f"audience: {audience}\n" if audience else ""
    path.write_text(PAGE.format(title=title, slug=slug, parent=parent, order=order,
                                features=features, audience=aud, sources=src, sha=sha, body=body))
    return path


def make_repo(tmp: Path) -> Path:
    tmp.mkdir(parents=True, exist_ok=True)
    git(tmp, "init", "-q")
    (tmp / "features" / "catalog").mkdir(parents=True)
    for fid in ("feat", "other"):
        (tmp / "features" / "catalog" / f"{fid}.json").write_text("{}")
    (tmp / "src").mkdir()
    (tmp / "src" / "a.py").write_text("x = 1\n")
    git(tmp, "add", "-A")
    git(tmp, "commit", "-qm", "base")
    return tmp
