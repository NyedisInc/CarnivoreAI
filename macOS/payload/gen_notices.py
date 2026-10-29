#!/usr/bin/env python3
"""Generate THIRD-PARTY-NOTICES for the app bundle (R2-15).

Read at build time from what the bundle really holds, never from a hand-kept list that can drift:
  - every wheel in runtime.lock, with the license name and text from the installed wheel's own dist-info
    (METADATA, License-File entries, and the bundled-library SBOM Pillow ships);
  - python-build-standalone, CPython, tmux and the libraries linked into them, from notices/recipe.json;
  - Electron's LICENSE and LICENSES.chromium.html from the electron package;
  - the app's production npm packages, from macOS/node_modules;
  - the browser side: the npm packages vite bundles into client/dist (its own module lists), the libraries vendored under
    client/vendor (notices/vendored.json) and the fonts under client/fonts (their license files).
Every locked wheel and every Mach-O file in the payload trees must resolve to a notice with a license name and
text, or the run fails (NoticeError) and the build stops. Standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECIPE = HERE / "notices" / "recipe.json"
TEXTS = HERE / "notices" / "texts"
LOCK = HERE / "runtime.lock"
VENDORED = HERE / "notices" / "vendored.json"
BUILD_SCRIPT = HERE / "build-payload.sh"
TREE_ARCHES = ("arm64", "x86_64")
MACH_O_MAGIC = {bytes.fromhex(h) for h in ("cefaedfe", "cffaedfe", "feedface", "feedfacf", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")}
LICENSE_FILE_RE = re.compile(r"^(licen[cs]e|copying|notice|unlicense)", re.I)


class NoticeError(Exception):
    pass


@dataclass
class Entry:

    kind: str
    name: str
    version: str
    license: str
    text: str
    used_in: str = ""


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()


PAYLOAD_ENV = {"sys_platform": "darwin", "platform_python_implementation": "CPython", "implementation_name": "cpython",
               "python_full_version": "3.12.15", "python_version": "3.12", "platform_system": "Darwin"}


def marker_applies(marker: str) -> bool:
    if " or " in marker:
        return True
    for clause in marker.split(" and "):
        m = re.fullmatch(r"\s*(\w+)\s*(==|!=|<=|>=|<|>)\s*'([^']*)'\s*", clause)
        if not m or m.group(1) not in PAYLOAD_ENV:
            return True
        have, op, want = PAYLOAD_ENV[m.group(1)], m.group(2), m.group(3)
        if m.group(1).startswith("python_") and op in ("<", ">", "<=", ">="):
            a, b = [tuple(int(x) for x in v.split(".")) for v in (have, want)]
            ok = {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        else:
            ok = (have == want) if op == "==" else (have != want) if op == "!=" else True
        if not ok:
            return False
    return True


def parse_lock(text: str) -> list[tuple[str, str]]:
    rows = []
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\]+)\s*(?:;\s*(.*?))?\s*\\?$", line)
        if m and (not m.group(3) or marker_applies(m.group(3))):
            rows.append((m.group(1), m.group(2)))
    return rows


def macho_files(tree: Path) -> list[str]:
    found = []
    for f in tree.rglob("*"):
        if f.is_symlink() or not f.is_file():
            continue
        with f.open("rb") as fh:
            if fh.read(4) in MACH_O_MAGIC:
                found.append(f.relative_to(tree).as_posix())
    return sorted(found)


def site_packages(tree: Path) -> Path:
    return tree / "python" / "lib" / "python3.12" / "site-packages"


def dist_infos(tree: Path) -> dict[str, Path]:
    out = {}
    for d in site_packages(tree).glob("*.dist-info"):
        out[norm(d.name[: -len(".dist-info")].rsplit("-", 1)[0])] = d
    return out


def metadata_fields(dist: Path) -> dict[str, list[str]]:
    fields: dict[str, list[str]] = {}
    for line in read_text(dist / "METADATA").split("\n\n", 1)[0].splitlines():
        if ": " in line and not line.startswith(" "):
            k, v = line.split(": ", 1)
            fields.setdefault(k, []).append(v.strip())
    return fields


def wheel_license_name(fields: dict[str, list[str]]) -> str:
    if fields.get("License-Expression"):
        return fields["License-Expression"][0]
    lic = (fields.get("License") or [""])[0]
    if lic and lic.upper() != "UNKNOWN" and len(lic) <= 80:
        return lic
    cls = [c.split("::")[-1].strip() for c in fields.get("Classifier", []) if c.startswith("License ::")]
    return " / ".join(cls)


def wheel_license_text(dist: Path, fields: dict[str, list[str]]) -> str:
    names = fields.get("License-File", [])
    files = []
    for n in names:
        for base in (dist / "licenses", dist):
            if (base / n).is_file():
                files.append((n, base / n))
                break
    if not files:
        for base in (dist / "licenses", dist):
            if base.is_dir():
                files += [(f.name, f) for f in sorted(base.iterdir()) if f.is_file() and LICENSE_FILE_RE.match(f.name)]
    return "\n\n".join(f"--- {n} ---\n{read_text(f)}" for n, f in files)


def wheel_entries(name: str, version: str, dist: Path, exclude: dict[str, str], fallbacks: dict[str, dict]) -> list[Entry]:
    fields = metadata_fields(dist)
    lic, text = wheel_license_name(fields), wheel_license_text(dist, fields)
    if not lic or not text:
        raise NoticeError(f"wheel {name} {version}: no license name or text in {dist.name}")
    entries = [Entry("wheel", name, version, lic, text, "site-packages")]
    crates: list[str] = []
    for sbom in sorted((dist / "sboms").glob("*.json")) if (dist / "sboms").is_dir() else []:
        for c in json.loads(sbom.read_text()).get("components", []):
            cname = c.get("name", "")
            if cname.startswith("PIL.") or cname in exclude:
                continue
            lics = c.get("licenses") or []
            ids = [x.get("license", {}).get("id", "") for x in lics if "license" in x]
            expr = " AND ".join(x["expression"] for x in lics if "expression" in x)
            if expr and not ids:
                crates.append(f"{cname} {c.get('version')} ({expr})")
                continue
            clic = " AND ".join(i for i in ids if i)
            fallback = fallbacks.get(cname.lower())
            if not clic and fallback:
                clic = fallback["license"]
                note = read_text(TEXTS / fallback["text_file"])
            elif clic:
                note = f"Full license text: see the {name} {version} entry above (its LICENSE file carries the text for the libraries bundled in the wheel)."
            else:
                raise NoticeError(f"{name}: bundled library {cname} has no license id in {sbom.name} and no sbom_license_fallback")
            entries.append(Entry("bundled", cname, c.get("version") or "unversioned", clic, note, f"bundled in the {name} wheel"))
    if crates:
        entries[0].text += ("\n\n--- Rust crates compiled into this wheel (from its own SBOM); each is available under the license expression shown ---\n"
                            + "\n".join(sorted(crates)))
    return entries


def pins_for(arch: str) -> dict[str, dict]:
    out = subprocess.run(["bash", str(BUILD_SCRIPT), "--pins", arch], check=True, capture_output=True, text=True).stdout
    return {c["name"]: c for c in json.loads(out)["components"]}


def expand(value: str, pins: dict[str, dict]) -> str:
    return re.sub(r"\{(\w+)\.(\w+)\}", lambda m: str(pins[m.group(1)][m.group(2)]), value)


def recipe_entries(recipe: dict, pins: dict[str, dict], tree: Path | None) -> dict[str, Entry]:
    out = {}
    for c in recipe["components"]:
        if "text_file" in c:
            f = TEXTS / c["text_file"]
            text = read_text(f) if f.is_file() else ""
        else:
            f = (tree / c["text_from_tree"]) if tree else None
            text = read_text(f) if f and f.is_file() else ""
        if not text or not c.get("license"):
            raise NoticeError(f"component {c['id']}: no license text or name")
        out[c["id"]] = Entry("component", c["name"], expand(c["version"], pins), c["license"], text, c["used_in"])
    return out


def record_owners(tree: Path) -> dict[str, str]:
    sp, owners = site_packages(tree), {}
    for d in sp.glob("*.dist-info"):
        rec = d / "RECORD"
        if not rec.is_file():
            continue
        dist = norm(d.name[: -len(".dist-info")].rsplit("-", 1)[0])
        for line in rec.read_text(errors="replace").splitlines():
            rel = line.rsplit(",", 2)[0].strip('"')
            if rel and not rel.startswith(".."):
                owners[(sp / rel).relative_to(tree).as_posix()] = dist
    return owners


def binary_owner(rel: str, owners: dict[str, str], rules: list[dict]) -> tuple[str, str] | None:
    if rel in owners:
        return ("wheel", owners[rel])
    for r in rules:
        if fnmatch.fnmatch(rel, r["glob"]):
            return ("component", r["component"])
    return None


def readme_license(pkg: Path) -> str:
    for name in ("README.md", "readme.md", "README"):
        f = pkg / name
        if f.is_file():
            m = re.search(r"^#*\s*License\s*\n[-=]*\s*\n(.+)", read_text(f), re.S | re.M | re.I)
            body = m.group(1).strip() if m else ""
            if "permission is hereby granted" in body.lower() or "licensed under" in body.lower():
                return f"--- {name} (License section; the package ships no LICENSE file) ---\n{body}"
    return ""


def npm_package_entry(d: Path, kind: str, used_in: str) -> Entry:
    m = json.loads((d / "package.json").read_text())
    lic = m.get("license") or (m.get("licenses") or [{}])[0].get("type") or ""
    if isinstance(lic, dict):
        lic = lic.get("type", "")
    files = [f for f in sorted(d.iterdir()) if f.is_file() and LICENSE_FILE_RE.match(f.name)]
    text = "\n\n".join(f"--- {f.name} ---\n{read_text(f)}" for f in files)
    if not text:
        text = readme_license(d)
    if not lic and files:
        low = text.lower()
        lic = next((f"{name} (named from the LICENSE text; package.json declares no license)" for needle, name in LICENSE_TEXT_NAMES if needle in low), "")
    if not text and lic == "MIT":
        author = m.get("author")
        author = author.get("name") if isinstance(author, dict) else author
        text = (f"--- standard MIT text; the package ships no license file, its package.json declares MIT ---\n"
                f"Copyright (c) {author or 'the ' + m['name'] + ' authors'}\n\n" + read_text(TEXTS / "mit-template.txt"))
    if not lic or not text:
        raise NoticeError(f"npm package {m.get('name')} {m.get('version')}: no license name or license file")
    return Entry(kind, m["name"], m["version"], lic, text, used_in)


def npm_entries(node_modules: Path, root_pkg: Path) -> list[Entry]:
    seen: dict[Path, Entry] = {}

    def find(frm: Path, name: str) -> Path:
        d = frm
        while True:
            cand = d / "node_modules" / name
            if (cand / "package.json").is_file():
                return cand
            if d == node_modules.parent or d.parent == d:
                raise NoticeError(f"npm package {name} (needed by {frm}) not found under {node_modules}")
            d = d.parent

    def visit(pkg_dir: Path, meta: dict) -> None:
        for dep in sorted({**meta.get("dependencies", {}), **meta.get("optionalDependencies", {})}):
            try:
                d = find(pkg_dir, dep)
            except NoticeError:
                if dep in meta.get("optionalDependencies", {}):
                    continue
                raise
            if d in seen:
                continue
            seen[d] = npm_package_entry(d, "npm", "app (macOS/node_modules)")
            m = json.loads((d / "package.json").read_text())
            visit(d, m)

    visit(root_pkg.parent, json.loads(root_pkg.read_text()))
    return sorted(seen.values(), key=lambda e: (e.name, e.version))


FONT_LICENSE_RE = re.compile(r"^(licen[cs]e|ofl|copying|attribution|notice)", re.I)
FONT_LICENSE_NAMES = (("sil open font license", "OFL-1.1"), ("attribution-sharealike 4.0", "CC-BY-SA-4.0"),
                      ("cc by-sa 4.0", "CC-BY-SA-4.0"))
LICENSE_TEXT_NAMES = (("permission is hereby granted, free of charge", "MIT"), ("apache license", "Apache-2.0"),
                      ("redistribution and use in source and binary forms", "BSD"), ("permission to use, copy, modify, and/or distribute", "ISC"))
VENDOR_DOC_FILES = {"VERSION.md", "README.md"}


def web_bundle_packages(web_dir: Path) -> list[dict]:
    if not (web_dir / "node_modules").is_dir():
        raise NoticeError(f"{web_dir}/node_modules is missing: run `npm ci` in web/ so the bundled packages can be listed")
    r = subprocess.run(["node", str(HERE / "web_bundle_modules.mjs"), str(web_dir)], capture_output=True, text=True)
    if r.returncode != 0:
        raise NoticeError(f"listing the web bundle's packages failed: {(r.stderr or r.stdout).strip()[-600:]}")
    return json.loads(r.stdout)["packages"]


def web_entries(packages: list[dict]) -> list[Entry]:
    return [npm_package_entry(Path(p["dir"]), "web", "browser bundle (client/dist, built from web/)") for p in packages]


def vendored_entries(client_dir: Path, vendored: dict) -> list[Entry]:
    gaps: list[str] = []
    comps = vendored["components"]
    root = client_dir / "vendor"
    for f in sorted(x for x in root.rglob("*") if x.is_file() and x.name not in VENDOR_DOC_FILES and x.name != ".DS_Store"):
        rel = f.relative_to(root).as_posix()
        if not any(fnmatch.fnmatch(rel, g) for c in comps for g in c["files"]):
            gaps.append(f"client/vendor/{rel}: no vendored.json component covers this file")
    out: list[Entry] = []
    for c in comps:
        used = c.get("used_in", "")
        if c.get("first_party"):
            out.append(Entry("vendored", c["name"], c["version"], c["license"], f"{c['name']} is Carnivore project code; it carries no third-party license.", used))
            continue
        tf = TEXTS / c["text_file"] if c.get("text_file") else None
        if tf is None or not tf.is_file() or len(read_text(tf).strip()) < 40 or not c.get("license"):
            gaps.append(f"vendored {c['name']} {c['version']}: no license name or license text")
            continue
        out.append(Entry("vendored", c["name"], c["version"], c["license"], read_text(tf), used))
    if gaps:
        raise NoticeError("\n  ".join(gaps))
    return out


def font_entries(client_dir: Path) -> list[Entry]:
    out: list[Entry] = []
    gaps: list[str] = []
    for d in sorted(x for x in (client_dir / "fonts").iterdir() if x.is_dir()):
        files = [f for f in sorted(d.iterdir()) if f.is_file() and FONT_LICENSE_RE.match(f.name)]
        text = "\n\n".join(f"--- {f.name} ---\n{read_text(f)}" for f in files)
        low = text.lower()
        lic = next((name for needle, name in FONT_LICENSE_NAMES if needle in low), "")
        if not files or not lic:
            gaps.append(f"font folder client/fonts/{d.name}: no recognizable license file beside the fonts")
            continue
        out.append(Entry("font", d.name, "-", lic, text, f"UI font (client/fonts/{d.name})"))
    if gaps:
        raise NoticeError("\n  ".join(gaps))
    return out


def electron_entries(dist: Path) -> list[Entry]:
    lic, chromium = dist / "LICENSE", dist / "LICENSES.chromium.html"
    if not lic.is_file() or not chromium.is_file():
        raise NoticeError(f"Electron LICENSE or LICENSES.chromium.html missing in {dist}")
    ver = read_text(dist / "version") if (dist / "version").is_file() else "unknown"
    return [
        Entry("electron", "Electron", ver, "MIT", read_text(lic), "the app shell"),
        Entry("electron", "Chromium and its third-party components", ver, "see LICENSES.chromium.html (BSD-3-Clause and many others)",
              "The complete license texts for Chromium and everything it bundles are in the file LICENSES.chromium.html, shipped beside this file in Contents/Resources.",
              "inside the Electron framework"),
    ]


def build_notices(*, trees: list[Path], recipe: dict, lock_text: str, pins: dict[str, dict], electron_dist: Path | None = None,
                  node_modules: Path | None = None, app_package: Path | None = None,
                  web_packages: list[dict] | None = None, client_dir: Path | None = None) -> list[Entry]:
    gaps: list[str] = []
    comps = recipe_entries(recipe, pins, trees[0] if trees else None)
    entries: list[Entry] = []
    wheels = parse_lock(lock_text)
    locked = {norm(n) for n, _ in wheels}
    used_components: set[str] = set()
    seen_wheel: set[str] = set()
    for tree in trees:
        infos = dist_infos(tree)
        for name, ver in wheels:
            key = norm(name)
            if key in seen_wheel:
                continue
            if key not in infos:
                gaps.append(f"locked wheel {name}=={ver} is not installed in {tree.name}")
                continue
            try:
                entries += wheel_entries(name, ver, infos[key], recipe.get("sbom_exclude", {}), recipe.get("sbom_license_fallback", {}))
                seen_wheel.add(key)
            except NoticeError as e:
                gaps.append(str(e))
        owners = record_owners(tree)
        for rel in macho_files(tree):
            owner = binary_owner(rel, owners, recipe["binary_rules"])
            if owner is None:
                gaps.append(f"{tree.name}/{rel}: no notice covers this binary")
            elif owner[0] == "wheel" and owner[1] not in locked:
                gaps.append(f"{tree.name}/{rel}: belongs to {owner[1]}, which is not in runtime.lock")
            elif owner[0] == "component":
                if owner[1] not in comps:
                    gaps.append(f"{tree.name}/{rel}: rule names unknown component {owner[1]}")
                used_components.add(owner[1])
    entries = sorted(comps.values(), key=lambda e: e.name.lower()) + entries
    if electron_dist is not None:
        try:
            entries += electron_entries(electron_dist)
        except NoticeError as e:
            gaps.append(str(e))
    if node_modules is not None and app_package is not None:
        try:
            entries += npm_entries(node_modules, app_package)
        except NoticeError as e:
            gaps.append(str(e))
    if web_packages is not None:
        try:
            entries += web_entries(web_packages)
        except NoticeError as e:
            gaps.append(str(e))
    if client_dir is not None:
        for fn in (lambda: vendored_entries(client_dir, json.loads(VENDORED.read_text())), lambda: font_entries(client_dir)):
            try:
                entries += fn()
            except NoticeError as e:
                gaps.append(str(e))
    if gaps:
        raise NoticeError("notices do not cover the bundle:\n  " + "\n  ".join(gaps))
    return entries


def render(entries: list[Entry], recipe: dict) -> str:
    out = ["THIRD-PARTY NOTICES FOR CARNIVORE", "",
           "Carnivore includes the third-party software listed below. Each entry gives the name, version, license and the",
           "license text. This file is generated at build time from the build's own inputs; it is not edited by hand.", "",
           "INDEX", ""]
    out += [f"  {e.name} {e.version} - {e.license}" for e in entries]
    out += ["", "NOT SHIPPED / SYSTEM", "", "  " + recipe.get("system_libraries_not_shipped", "")]
    out += [f"  {k}: {v}" for k, v in recipe.get("sbom_exclude", {}).items()]
    for e in entries:
        out += ["", "=" * 78, f"== {e.name} {e.version} | {e.license} | {e.kind}" + (f" | {e.used_in}" if e.used_in else ""), "=" * 78, "", e.text]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--tree", action="append", required=True, type=Path)
    ap.add_argument("--electron-dist", type=Path)
    ap.add_argument("--chromium-out", type=Path, help="folder that receives LICENSES.chromium.html")
    ap.add_argument("--node-modules", type=Path)
    ap.add_argument("--app-package", type=Path)
    ap.add_argument("--web-dir", type=Path, help="web/ folder: its bundled npm packages are listed by vite and get notices")
    ap.add_argument("--client-dir", type=Path, help="client/ folder: vendored libraries and fonts get notices")
    a = ap.parse_args(argv)
    recipe = json.loads(RECIPE.read_text())
    try:
        web_packages = web_bundle_packages(a.web_dir) if a.web_dir else None
        entries = build_notices(trees=a.tree, recipe=recipe, lock_text=LOCK.read_text(), pins=pins_for("arm64"),
                                electron_dist=a.electron_dist, node_modules=a.node_modules, app_package=a.app_package,
                                web_packages=web_packages, client_dir=a.client_dir)
    except NoticeError as e:
        print(f"gen_notices: {e}", file=sys.stderr)
        return 1
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render(entries, recipe), encoding="utf-8")
    if a.electron_dist and a.chromium_out:
        shutil.copyfile(a.electron_dist / "LICENSES.chromium.html", a.chromium_out / "LICENSES.chromium.html")
    print(f"gen_notices: {len(entries)} notices -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
