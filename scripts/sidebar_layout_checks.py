
from __future__ import annotations

from pathlib import Path

TOL = 0.5

GEOMETRY_JS = """() => {
  const list = document.getElementById('session-sidebar-list');
  const box = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return {x: b.x, y: b.y, w: b.width, h: b.height, right: b.right, bottom: b.bottom}; };
  const headers = Array.from(list.querySelectorAll('.session-sidebar-group__headerrow')).map((row) => ({
    label: (row.querySelector('.session-sidebar-group__label') || {}).textContent || '',
    row: box(row),
    chevron: box(row.querySelector('.session-sidebar-group__chevron')),
    labelBox: box(row.querySelector('.session-sidebar-group__label')),
    led: box(row.querySelector('.session-sidebar-group__aggregate .status-led')),
    slot: box(row.querySelector('.session-sidebar-group__aggregate')),
  }));
  const rows = Array.from(list.querySelectorAll('.session-sidebar-row')).map((r) => ({
    name: r.dataset.name, row: box(r), led: box(r.querySelector('.status-led')),
  }));
  const projects = list.querySelector('.session-sidebar-projects');
  const cs = projects ? getComputedStyle(projects) : null;
  return {headers, rows,
    projects: projects ? {box: box(projects), borderTop: parseFloat(cs.borderTopWidth),
      header: box(projects.querySelector('.session-sidebar-group__headerrow'))} : null,
    prev: projects && projects.previousElementSibling ? box(projects.previousElementSibling) : null};
}"""


def _spread(values: list[float]) -> float:
    return (max(values) - min(values)) if len(values) > 1 else 0.0


def measure_header_layout(page, rep, tag: str) -> dict:
    m = page.evaluate(GEOMETRY_JS)
    heads = [h for h in m["headers"] if h["chevron"]]
    chev = [h["chevron"]["x"] for h in heads]
    rep.check(len(heads) > 3 and _spread(chev) <= TOL, f"[{tag}] every header chevron has one x",
              f"n={len(heads)} x={min(chev):.2f}..{max(chev):.2f}")
    leds = [h["led"]["x"] for h in heads if h["led"]]
    rep.check(len(leds) > 3 and _spread(leds) <= TOL, f"[{tag}] every header aggregate light has one x",
              f"n={len(leds)} x={min(leds):.2f}..{max(leds):.2f}")
    right_of_label = all(h["led"]["x"] >= h["labelBox"]["right"] - TOL for h in heads if h["led"])
    rep.check(right_of_label, f"[{tag}] the aggregate light sits right of the name")
    chev_before_label = all(h["chevron"]["right"] <= h["labelBox"]["x"] + TOL for h in heads)
    rep.check(chev_before_label, f"[{tag}] the chevron leads the name")
    rleds = [r["led"]["x"] for r in m["rows"] if r["led"]]
    rep.check(len(rleds) > 3 and _spread(rleds) <= TOL, f"[{tag}] every row light has one x",
              f"n={len(rleds)} x={min(rleds):.2f}..{max(rleds):.2f}")
    rep.check(bool(rleds) and min(rleds) > max(chev), f"[{tag}] row lights are inset right of the header chevrons",
              f"row light x={min(rleds):.2f} chevron x={max(chev):.2f}")
    rows_x = [r["row"]["x"] for r in m["rows"]]
    head_x = min(h["row"]["x"] for h in heads)
    inset = min(rows_x) - head_x
    rep.check(_spread(rows_x) <= TOL and 8 <= inset <= 12,
              f"[{tag}] every row is inset from the headers by one token (8-12px)",
              f"row x={min(rows_x):.2f}..{max(rows_x):.2f} header x={head_x:.2f} inset={inset:.2f}")
    p = m["projects"]
    rep.check(p is not None and p["borderTop"] >= 1, f"[{tag}] a rule is drawn above PROJECTS",
              f"border-top={p and p['borderTop']}")
    if p and m["prev"]:
        rep.check(p["box"]["y"] >= m["prev"]["bottom"] - TOL and p["header"]["y"] > p["box"]["y"],
                  f"[{tag}] the rule sits between the last section and the PROJECTS header",
                  f"prev bottom={m['prev']['bottom']:.1f} rule y={p['box']['y']:.1f} header y={p['header']['y']:.1f}")
    return m


def renamed_fixture(fixture: dict, *, with_uuids: bool = True) -> dict:
    def new(name: str) -> str:
        return "carnivore_" + name[len("cloude_"):] if name.startswith("cloude_") else name

    def uuid(name: str) -> str:
        return "U-" + new(name)

    rows = []
    for r in fixture["rows"]:
        row = dict(r, name=new(r["name"]))
        rows.append(row)
    records = [{"session_uuid": uuid(r["name"]), "tmux_name": r["name"],
                "tmux_created_epoch": r.get("created_at_epoch")} for r in rows]
    groups = []
    for g in fixture["groups"]:
        group = dict(g, members=list(g["members"]))
        if with_uuids:
            group["member_session_uuids"] = [uuid(m) for m in g["members"]]
        groups.append(group)
    return {"rows": rows, "groups": groups, "records": records}


def expected_by_group(fixture: dict) -> dict:
    live = {r["name"] for r in fixture["rows"]}
    out = {}
    for g in fixture["groups"]:
        names = [m for m in g["members"] if m in live]
        out["g:" + g["uuid"]] = ["carnivore_" + n[len("cloude_"):] if n.startswith("cloude_") else n for n in names]
    return out


def measure_renamed(open_page, browser, port, fixture: dict, rep, shots: Path, measure_js: str) -> None:
    want = expected_by_group(fixture)
    filed = {n for names in want.values() for n in names}
    page = open_page(browser, port, renamed_fixture(fixture))
    m = page.evaluate(measure_js)
    for key, names in want.items():
        got = (m.get(key) or {}).get("rows", [])
        rep.check(got == names, f"RENAMED: group {m.get(key, {}).get('label')} keeps every member, in member order",
                  f"got={got} want={names}")
    other = (m.get("other") or {}).get("rows", [])
    rep.check(not (set(other) & filed), "RENAMED: no renamed member falls into ungrouped", f"ungrouped={other}")
    page.screenshot(path=str(shots / "sidebar-renamed-grouped.png"))
    page.locator("#session-sidebar-panel").screenshot(path=str(shots / "sidebar-renamed-grouped-panel.png"))
    page.close()

    page = open_page(browser, port, renamed_fixture(fixture, with_uuids=False))
    m = page.evaluate(measure_js)
    other = (m.get("other") or {}).get("rows", [])
    rep.check(filed <= set(other),
              "NEGATIVE CONTROL: without member_session_uuids the renamed rows fall into ungrouped",
              f"ungrouped={len(other)} filed={len(filed)}")
    page.screenshot(path=str(shots / "sidebar-renamed-negative-control.png"))
    page.close()
