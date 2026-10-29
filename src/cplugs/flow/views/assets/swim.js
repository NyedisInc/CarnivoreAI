"use strict";
function renderSwim(root) {
  const LABW = 190, LANEH = 98, AXH = 30, CW = 176, CH = 62, RW = 150, RH = 28, STEP = 34, GAPC = 12, PADL = 16, STRIP = 9;
  const order = []; (function walk(id) { order.push(id); (kids[id] || []).forEach(walk); })(rootId);
  const laneY = {}; order.forEach((id, i) => { laneY[id] = AXH + i * LANEH; });
  const panel = el("section", "panel"), sc = el("div", "sw-scroll"), board = el("div", "sw-board"); panel.append(panelHead("Swimlane Conversation + Task Timeline"), sc); sc.append(board);
  const cards = [];
  const TITLE = { task_created: "Create task", delegate: "Delegate", chat: "Comment", task_updated: "Update status", task_done: "Complete", return: "Return findings" };
  D.events.forEach(r => {
    const title = r.kind === "delegate" && r.to ? "Delegate to " + ag[r.to].name : (r.edge_kind === "subagent_return" ? "Return result" : (r.kind === "task_created" && !taskById[r.task].root ? "Create subtask" : TITLE[r.kind]));
    const body = r.quote || (r.task ? taskById[r.task].title : "");
    cards.push({ r, lane: r.from, t: r.t, w: CW, h: CH, title, body, send: true });
    if (r.to && r.to !== r.from) cards.push({ r, lane: r.to, t: Math.max(r.t_to, r.t), w: RW, h: RH, recv: true });
  });
  cards.sort((a, b) => a.t - b.t || (a.recv ? 1 : 0) - (b.recv ? 1 : 0));
  const lastRight = {}; let prevX = PADL + CW / 2 - STEP;
  cards.forEach(c => { const x = Math.max(prevX + STEP, (lastRight[c.lane] == null ? PADL : lastRight[c.lane] + GAPC) + c.w / 2); c.x = x; prevX = x; lastRight[c.lane] = x + c.w / 2; });
  const plotW = Math.max(...cards.map(c => c.x + c.w / 2), 400) + 24, W = LABW + plotW, H = AXH + order.length * LANEH;
  board.style.width = W + "px"; board.style.height = H + "px";
  order.forEach(id => { const a = ag[id], lane = el("div", "sw-lane"), y = laneY[id]; lane.style.cssText = `top:${y}px;height:${LANEH}px;--c:${col[id]}`; board.append(lane);
    const lab = el("div", "sw-lab", `<div class="av sm">${esc(a.mono)}</div><div><div class="nm">${esc(a.name)}</div><div class="ds">${esc(a.role)}</div></div>`); lab.style.cssText = `height:${LANEH}px;--c:${col[id]}`; lane.append(lab); });
  const axis = el("div", "sw-axis"); axis.style.width = W + "px"; axis.innerHTML = `<span class="tk mono" style="left:12px;transform:none">Time</span>`; board.append(axis);
  let lastTick = -1e9, lastLab = ""; cards.filter(c => c.send).forEach(c => { if (c.x - lastTick < 70 || c.r.time === lastLab) return; lastTick = c.x; lastLab = c.r.time; const x = LABW + c.x;
    axis.insertAdjacentHTML("beforeend", `<span class="tk mono" style="left:${x}px">${esc(c.r.time)}</span>`); const l = el("div", "sw-tickline"); l.style.cssText = `left:${x}px;height:${H - AXH}px`; board.append(l); });
  cards.forEach(c => {
    const y = laneY[c.lane] + (LANEH - c.h) / 2, k = KIND[c.r.kind], d = el("div", "sw-card" + (c.recv ? " recv" : ""));
    d.style.cssText = `left:${LABW + c.x - c.w / 2}px;top:${y}px;width:${c.w}px;height:${c.h}px;--c:${col[c.lane]}`;
    if (c.recv) d.innerHTML = `${icon("arrow", col[c.r.from])}<span>${c.r.edge_kind === "subagent_return" || c.r.cls === "return" ? "Result from " : "From "}${esc(ag[c.r.from].name)}</span>`;
    else d.innerHTML = `<div class="h">${icon(k[0], k[1])}<span>${esc(c.title)}</span>${c.r.task ? `<span class="id">${esc(c.r.task)}</span>` : ""}</div><div class="b">${esc(c.body)}</div>`;
    d.title = `${c.r.time} ${c.r.text.map(p => typeof p === "string" ? p : ag[p.a].name).join("")}`; board.append(d); c.el = d;
  });
  const svg = svgEl("svg", { class: "sw-arrows", width: W, height: H }), defs = svgEl("defs"); svg.append(defs); board.append(svg);
  const spans = {}; cards.forEach(c => (spans[c.lane] = spans[c.lane] || []).push([LABW + c.x - c.w / 2 - 8, LABW + c.x + c.w / 2 + 8]));
  const free = (x, from, to) => { for (let i = Math.min(from, to) + 1; i < Math.max(from, to); i++) if ((spans[order[i]] || []).some(([a, b]) => x >= a && x <= b)) return false; return true; };
  const idx = {}; order.forEach((id, i) => { idx[id] = i; });
  cards.filter(c => c.send && c.r.to && c.r.to !== c.r.from).forEach((s, n) => {
    const rc = cards.find(c => c.recv && c.r === s.r), a = idx[s.lane], b = idx[rc.lane], down = b > a, xs = LABW + s.x, xr = LABW + rc.x;
    let xv = xs; for (let k = 0; k < 400 && !free(xv, a, b); k++) xv = xs + (k % 2 ? -1 : 1) * Math.ceil((k + 1) / 2) * 6; if (!free(xv, a, b)) xv = xs;
    const sy = laneY[s.lane] + (down ? LANEH - STRIP : STRIP), ry = laneY[rc.lane] + (down ? STRIP : LANEH - STRIP), cyS = laneY[s.lane] + LANEH / 2 + (down ? s.h / 2 : -s.h / 2), cyR = laneY[rc.lane] + LANEH / 2 + (down ? -RH / 2 : RH / 2);
    const pts = [[xs, cyS], [xs, sy], [xv, sy], [xv, ry], [xr, ry], [xr, cyR]];
    const cls = s.r.cls, dash = cls ? isDash(cls) : s.r.kind !== "delegate", color = cls ? arrowColor(cls, s.r.to) : col[s.r.to];
    arrow(svg, defs, "w" + n, pts.filter((p, i) => i === 0 || p[0] !== pts[i - 1][0] || p[1] !== pts[i - 1][1]), color, dash, s.r.quote || s.r.kind, null);
  });
  panel.append(el("div", "note mono", "Cards run in time order, left to right; idle stretches are left out, so spacing is not to scale. Solid arrow: delegated. Dashed arrow: returned or shared."));
  root.append(panel);
  return { fit() {} };
}
