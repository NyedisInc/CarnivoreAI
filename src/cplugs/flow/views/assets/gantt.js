"use strict";
function renderGantt(root) {
  const ROWH = 30, AXH = 34, BARH = 14, SEGH = 8, GAPPX = 46, CALLW = 210, CALLH = 62, TICKS = [60, 120, 300, 600, 900, 1800, 3600, 7200];
  const collapsed = new Set();
  const panel = el("section", "panel"), grid = el("div", "gt-grid"), tree = el("div", "gt-tree"), plot = el("div", "gt-plot");
  const ctl = seg("Tree", [["open", "Expand all"], ["closed", "Collapse all"]], "open", v => { collapsed.clear(); if (v === "closed") D.agents.forEach(a => { if (tasksOf(a.id).length) collapsed.add(a.id); }); build(); });
  panel.append(panelHead("Agent / Task Gantt", ctl), grid); grid.append(tree, plot); root.append(panel);
  const legend = el("div", "gt-legend");
  const lg = (inner, text) => `<span><svg viewBox="0 0 34 12">${inner}</svg>${text}</span>`;
  legend.innerHTML = lg('<rect x="1" y="1" width="32" height="10" rx="2" style="fill:var(--c1)"/>', "Task duration") + lg('<rect x="1" y="4" width="32" height="5" rx="2" style="fill:var(--c1);fill-opacity:.55"/>', "Agent work") +
    lg('<path d="M1 6h26M22 2l6 4-6 4" fill="none" stroke="var(--upd)" stroke-width="1.8"/>', "Delegated") + lg('<path d="M1 6h26M22 2l6 4-6 4" fill="none" stroke="var(--ctx)" stroke-width="1.8" stroke-dasharray="5 4"/>', "Returned") +
    lg('<path d="M17 1l6 5-6 5-6-5z" fill="var(--ok)"/>', "Milestone (done, review)");
  panel.append(legend);
  const order = []; (function walk(id) { order.push(id); (kids[id] || []).forEach(walk); })(rootId);
  const status = id => { const l = tasksOf(id); return !l.length ? null : (l.every(t => t.status === "done") ? "done" : "in_progress"); };
  function rows() {
    const out = []; order.forEach(id => { out.push({ id, grp: true }); if (!collapsed.has(id)) tasksOf(id).slice().sort((a, b) => a.t - b.t).forEach(t => out.push({ id, task: t })); }); return out;
  }
  function scale(width) {
    const gaps = (D.idle_gaps || []).filter(g => g.end > T0 && g.start < T1).map(g => ({ s: Math.max(g.start, T0), e: Math.min(g.end, T1) })).filter(g => g.e - g.s > 0);
    const busy = (T1 - T0) - gaps.reduce((s, g) => s + (g.e - g.s), 0), pw = width - 24 - gaps.length * GAPPX, k = Math.max(.0001, pw / Math.max(1, busy));
    const X = t => { let x = 12, prev = T0; for (const g of gaps) { if (t <= g.s) break; x += (Math.min(t, g.s) - prev) * k; if (t >= g.e) { x += GAPPX; prev = g.e; } else { return x + (t - g.s) / (g.e - g.s) * GAPPX; } } return x + (t - prev) * k; };
    return { X, gaps, k };
  }
  function build() {
    const list = rows(), width = Math.max(300, plot.clientWidth || 800), sc = scale(width), X = sc.X;
    tree.innerHTML = `<div class="gt-head"><span>Agent / Task</span><span>Status</span></div>`;
    const rowY = {}, headY = {};
    list.forEach((r, i) => {
      const y = AXH + i * ROWH + ROWH / 2; let div;
      if (r.grp) {
        const a = ag[r.id], n = tasksOf(r.id).length, s = status(r.id); headY[r.id] = y;
        div = el("div", "gt-row grp", `${n ? `<button class="caret" type="button" aria-label="${collapsed.has(r.id) ? "Expand" : "Collapse"} ${esc(a.name)}">${collapsed.has(r.id) ? "+" : "-"}</button>` : `<span class="dot" style="--c:${col[r.id]}"></span>`}<span class="nm" title="${esc(a.full)}">${esc(a.name)}</span>${s ? pill(s) : ""}`);
        const cb = div.querySelector(".caret"); if (cb) cb.onclick = () => { collapsed.has(r.id) ? collapsed.delete(r.id) : collapsed.add(r.id); build(); };
      } else {
        rowY[r.task.id] = y;
        div = el("div", "gt-row task", `<span class="dot" style="--c:${col[r.id]}"></span><span class="nm" title="${esc(r.task.title)}"><span class="ref">${esc(r.task.id)}</span> ${esc(r.task.title)}</span>${pill(r.task.status)}`);
      }
      tree.append(div);
    });
    const rowsH = AXH + list.length * ROWH, calls = pickCallouts(X, width), bandH = calls.rows ? calls.rows * (CALLH + 8) + 16 : 0, H = rowsH + bandH;
    plot.innerHTML = ""; const svg = svgEl("svg", { viewBox: `0 0 ${width} ${H}`, height: H, width: "100%" }); const defs = svgEl("defs"); svg.append(defs); plot.append(svg);
    const step = TICKS.find(s => s * sc.k >= 78) || TICKS[TICKS.length - 1], off = D.tz_offset;
    for (let t = Math.ceil((T0 + off) / step) * step - off; t <= T1; t += step) {
      if (sc.gaps.some(g => t > g.s && t < g.e)) continue; const x = X(t);
      svg.append(svgEl("line", { x1: x, x2: x, y1: AXH - 6, y2: rowsH, class: "grid" })); const tx = svgEl("text", { x: x + 3, y: 14 }); tx.textContent = hhmm(t); svg.append(tx);
    }
    sc.gaps.forEach(g => { const xa = X(g.s), xb = X(g.e); [xa, xb].forEach(x => svg.append(svgEl("line", { x1: x, x2: x, y1: 0, y2: rowsH, class: "gapmark" })));
      const m = Math.round((g.e - g.s) / 60), tx = svgEl("text", { x: (xa + xb) / 2, y: 26, "text-anchor": "middle" }); tx.textContent = "idle " + (m >= 90 ? (m / 60).toFixed(1) + "h" : m + "m"); svg.append(tx); });
    list.forEach((r, i) => svg.append(svgEl("line", { x1: 0, x2: width, y1: AXH + (i + 1) * ROWH, y2: AXH + (i + 1) * ROWH, class: "grid" })));
    const ya = (id, task) => (task && rowY[task] != null && taskById[task].agent === id) ? rowY[task] : headY[id];
    D.events.filter(r => r.to && r.edge_kind !== "mark").forEach((r, n) => {
      const ys = headY[r.from], yt = ya(r.to, r.task), xs = X(r.t), xt = Math.max(X(r.t_to), xs); if (ys == null || yt == null) return;
      const dash = r.cls ? isDash(r.cls) : r.kind !== "delegate", color = r.cls ? arrowColor(r.cls, r.to) : col[r.to];
      const x2 = xt <= xs + 2 ? xs + 3 : xt, pts = [[xs, ys], [xs, yt], [x2, yt]];
      arrow(svg, defs, "g" + n, pts, color, dash, r.quote || r.kind, null).style.opacity = ".75";
    });
    order.forEach(id => (D.segments[id] || []).forEach(([a, b]) => { const y = headY[id]; svg.append(svgEl("rect", { x: X(a), y: y - SEGH / 2, width: Math.max(3, X(b) - X(a)), height: SEGH, rx: 2, class: "seg", style: "--c:" + col[id] })); }));
    list.filter(r => r.task).forEach(r => {
      const t = r.task, y = rowY[t.id], x = X(t.t), w = Math.max(10, X(t.end) - x), g = svgEl("g"), rc = svgEl("rect", { x, y: y - BARH / 2, width: w, height: BARH, rx: 3, class: "bar", style: "--c:" + col[r.id] });
      const tt = svgEl("title"); tt.textContent = `${t.id} ${t.title} (${STATUS[t.status]}, ${t.time})`; rc.append(tt); g.append(rc);
      if (w > 34) { const lab = svgEl("text", { x: x + 5, y: y + 3.5, class: "barlab" }); lab.textContent = t.id; g.append(lab); } svg.append(g);
    });
    D.events.filter(r => r.kind === "task_done" || (r.kind === "task_updated" && r.acts[0].col === "review")).forEach(r => {
      const own = r.task && taskById[r.task], y = r.task && rowY[r.task] != null ? rowY[r.task] : headY[own ? own.agent : r.from], x = X(r.t); if (y == null) return;
      const m = svgEl("path", { d: `M${x} ${y - 8}l7 8-7 8-7-8z`, class: "ms", style: "fill:" + (r.kind === "task_done" ? "var(--ok)" : "var(--upd)") }); const tt = svgEl("title"); tt.textContent = `${r.time} ${r.text.map(p => typeof p === "string" ? p : ag[p.a].name).join("")}`; m.append(tt); svg.append(m);
    });
    if (calls.items.length) {
      const lab = svgEl("text", { x: 12, y: rowsH + 12 }); lab.textContent = `messages (${calls.items.length} of ${calls.total}; the chat view has all)`; svg.append(lab);
      calls.items.forEach(c => { const x = Math.max(4, Math.min(width - CALLW - 4, c.x - CALLW / 2)), y = rowsH + 20 + c.row * (CALLH + 8);
        const fo = svgEl("foreignObject", { x, y, width: CALLW, height: CALLH }); const d = el("div", "gt-call", `<b>${esc(ag[c.r.from].name)}</b><span class="t mono">${esc(c.r.time)}</span><q>${esc(c.r.quote)}</q>`);
        d.style.cssText = `position:static;--bw:100%;--c:${col[c.r.from]};height:${CALLH}px`; fo.append(d); svg.append(fo);
        svg.append(svgEl("path", { d: `M${c.x} ${y - 6}l-4 6h8z`, style: "fill:" + col[c.r.from] })); });
    }
  }
  function pickCallouts(X, width) {
    const msgs = D.events.filter(r => r.quote && ["crosstalk", "huddle_post", "owner_reply"].includes(r.edge_kind)), maxRows = 3, ends = [], items = [];
    msgs.forEach(r => { const x = X(r.t), left = Math.max(4, Math.min(width - CALLW - 4, x - CALLW / 2)); const row = ends.findIndex(e => left >= e + 8); const pick = row >= 0 ? row : (ends.length < maxRows ? ends.length : -1);
      if (pick < 0) return; ends[pick] = left + CALLW; items.push({ r, x, row: pick }); });
    return { items, rows: ends.length, total: msgs.length };
  }
  return { fit: build };
}
