"use strict";
function renderHybrid(root) {
  const NW = 250, NH = 96, CW = 200, CH = 96, GAP = 12, COLG = 44, PORT = 46, ROW = NH, CHAN = 190, FW = 220, FH = 84, PADX = 10, PADY = 10, SLOT = 36;
  const cols = el("div", "hy-cols"); root.append(cols);
  const tlPanel = el("section", "panel"), tl = el("ol", "tl");
  tlPanel.append(panelHead("Event Timeline", el("span", "cnt mono", D.events.length + " events")));
  tlPanel.firstChild.insertAdjacentHTML("afterbegin", icon("clock", "var(--accent)").replace("<svg ", '<svg class="hi" '));
  D.events.forEach(r => {
    const k = KIND[r.kind], li = el("li", "", `<span class="tm mono">${esc(r.time)}</span><span class="ic">${icon(k[0], k[1])}</span><span class="tx">${sentence(r)}</span>`);
    if (r.edge) li.dataset.edge = r.edge; if (r.task) li.dataset.task = r.task; tl.append(li);
  });
  tlPanel.append(tl);
  const gPanel = el("section", "panel"), gs = el("div", "gscroll"), stage = el("div"), svg = svgEl("svg", { id: "edges" });
  stage.id = "stage"; stage.dataset.view = "full"; stage.append(svg); gs.append(stage);
  const views = seg("View", [["full", "Full Flow"], ["task", "Task Status"], ["agent", "Agent View"]], "full", v => { stage.dataset.view = v; });
  gPanel.append(panelHead("Agent Flow / Delegation Graph", views), gs);
  const note = el("div", "note mono", "Solid arrow: delegated. Dashed arrow: returned or shared. Source: the flow collector, read-only." +
    (D.offtree ? ` ${D.offtree} message(s) between agents that are not parent and child appear in the timeline only.` : ""));
  gPanel.append(note); cols.append(tlPanel, gPanel);
  let leaf = 0; const colOf = {}, depth = {};
  (function walk(id, d) { depth[id] = d; const k = kids[id] || []; if (!k.length) { colOf[id] = leaf++; return; } k.forEach(c => walk(c, d + 1)); colOf[id] = (colOf[k[0]] + colOf[k[k.length - 1]]) / 2; })(rootId, 0);
  const CELL = NW + GAP + CW + COLG, maxD = Math.max(...Object.values(depth));
  const pos = {}; D.agents.forEach(a => { pos[a.id] = { x: PADX + colOf[a.id] * CELL, y: PADY + depth[a.id] * (ROW + CHAN) }; });
  [["nw", NW], ["nh", NH], ["cw", CW], ["ch", CH], ["fw", FW], ["fh", FH]].forEach(([k, v]) => stage.style.setProperty("--" + k, v + "px"));
  const W = PADX * 2 + leaf * CELL - COLG, H = PADY * 2 + (maxD + 1) * ROW + maxD * CHAN;
  stage.style.width = W + "px"; stage.style.height = H + "px"; svg.setAttribute("width", W); svg.setAttribute("height", H);
  D.agents.forEach(a => {
    const p = pos[a.id], n = el("div", "node", `<div class="av">${esc(a.mono)}</div><div><div class="nm">${esc(a.name)}</div><div class="rl mono">${esc(a.role)}</div><div class="ds">${esc(a.desc)}</div></div>`);
    n.style.cssText += `left:${p.x}px;top:${p.y}px;--c:${col[a.id]}`; n.title = a.full; n.dataset.agent = a.id; stage.append(n);
    const t = cardTask(a.id);
    if (t) { const cd = taskCard(t); cd.style.cssText += `left:${p.x + NW + GAP}px;top:${p.y}px`; stage.append(cd); }
  });
  const rp = pos[rootId], fx = rp.x + CELL, fy = rp.y + (NH - FH) / 2;
  if (D.final) { const fin = el("div", "final", `${icon("task", "var(--accent)")}<div><b>${esc(D.final.title)}</b><span>${esc(D.final.text)}</span></div>`); fin.style.cssText += `left:${fx}px;top:${fy}px`; stage.append(fin); }
  const defs = svgEl("defs"); svg.append(defs); const drawn = [], ORDER = { delegate: 0, return: 1, context: 2 };
  function draw(id, pts, color, dash, label, lx, ly, extra) {
    const g = svgEl("g"); svg.append(g); const p = arrow(g, defs, id, pts, color, dash, label, extra);
    const lb = el("div", "elab", esc(label)); lb.style.cssText = `left:${lx}px;top:${ly}px;--c:${color}`; stage.append(lb); drawn.push({ g, lb, id });
  }
  const byParent = {};
  D.edges.forEach(e => { const up = ag[e.from].parent === e.to; e._par = up ? e.to : e.from; e._ch = up ? e.from : e.to; e._up = up; (byParent[e._par] = byParent[e._par] || []).push(e); });
  const cx = id => pos[id].x + NW / 2;
  Object.entries(byParent).forEach(([par, list]) => {
    list.sort((a, b) => cx(a._ch) - cx(b._ch) || ORDER[a.cls] - ORDER[b.cls]);
    const n = list.length; list.forEach((e, i) => { e._px = cx(par) + (i - (n - 1) / 2) * PORT; });
    const per = {}; list.forEach(e => { (per[e._ch] = per[e._ch] || []).push(e); });
    Object.values(per).forEach(g => g.forEach((e, j) => { e._tx = cx(e._ch) + (j - (g.length - 1) / 2) * PORT; }));
    const L = list.filter(e => e._tx < e._px - 3), R = list.filter(e => e._tx > e._px + 3), S = list.filter(e => Math.abs(e._tx - e._px) <= 3);
    L.forEach((e, i) => { e._slot = i; }); R.slice().reverse().forEach((e, i) => { e._slot = i; }); S.forEach((e, i) => { e._slot = i; });
    const y0 = pos[par].y + NH + 14, yBot = pos[par].y + NH + CHAN - 14;
    list.forEach(e => {
      const y = y0 + (e._slot + .5) * SLOT * Math.min(1, (yBot - y0) / (SLOT * Math.max(L.length, R.length, S.length, 1))), ty = pos[e._ch].y;
      let pts = [[e._px, pos[par].y + NH], [e._px, y], [e._tx, y], [e._tx, ty]]; if (Math.abs(e._tx - e._px) <= 3) pts = [[e._px, pos[par].y + NH], [e._tx, ty]];
      if (e._up) pts = pts.reverse();
      const span = Math.abs(e._tx - e._px), lx = span > 3 ? (e._px + e._tx) / 2 : e._px, ly = span > 3 ? y : pos[par].y + NH + 30 + e._slot * SLOT;
      draw(e.id, pts, arrowColor(e.cls, e._ch), isDash(e.cls), e.label, lx, ly);
    });
  });
  const kid = (kids[rootId] || [])[0], kt = kid && cardTask(kid);
  if (D.final && kt) {
    const kp = pos[kid], sx = kp.x + NW + GAP + CW, sy = kp.y + CH / 2, ex = fx + FW / 2;
    draw("final", [[sx, sy], [ex, sy], [ex, fy + FH]], "var(--accent)", true, "Final result to " + ag[rootId].name, ex, (sy + fy + FH) / 2, "fin");
    draw("final2", [[fx, fy + FH / 2], [rp.x + NW, fy + FH / 2]], "var(--accent)", true, "Callback", (fx + rp.x + NW) / 2, fy + FH / 2 - 16, "fin");
  }
  tl.querySelectorAll("li").forEach(li => {
    li.onmouseenter = () => { if (!li.dataset.edge) return; stage.classList.add("hlr"); drawn.forEach(d => { d.g.classList.toggle("on", d.id === li.dataset.edge); d.lb.style.opacity = d.id === li.dataset.edge ? 1 : .25; }); };
    li.onmouseleave = () => { stage.classList.remove("hlr"); drawn.forEach(d => { d.g.classList.remove("on"); d.lb.style.opacity = ""; }); };
  });
  const fit = () => { const s = Math.max(.6, Math.min(1, (gs.clientWidth - 32) / W)); stage.style.transform = `scale(${s})`; gs.style.height = (H * s + 42) + "px"; };
  return { fit };
}
