"use strict";
const D = JSON.parse(document.getElementById("d").textContent);
const NS = "http://www.w3.org/2000/svg";
const $ = (s, r = document) => r.querySelector(s);
const el = (t, c, h) => { const e = document.createElement(t); if (c) e.className = c; if (h != null) e.innerHTML = h; return e; };
const svgEl = (t, attrs) => { const e = document.createElementNS(NS, t); Object.entries(attrs || {}).forEach(([k, v]) => e.setAttribute(k, v)); return e; };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const ag = {}, col = {}, kids = {}, taskById = {};
D.agents.forEach((a, i) => { ag[a.id] = a; col[a.id] = "var(--c" + (i % 8) + ")"; });
D.agents.forEach(a => { if (a.parent) (kids[a.parent] = kids[a.parent] || []).push(a.id); });
D.tasks.forEach(t => { taskById[t.id] = t; });
const rootId = (D.agents.find(a => !a.parent) || D.agents[0]).id;
const tasksOf = id => D.tasks.filter(t => t.agent === id);
const cardTask = id => { const l = tasksOf(id); return l.find(t => t.root) || l[0]; };
const T0 = D.window.start, T1 = D.window.end;
const evAt = D.events.slice().sort((a, b) => a.t - b.t);
const hhmm = t => { const d = new Date((t + D.tz_offset) * 1000), p = n => String(n).padStart(2, "0"); return p(d.getUTCHours()) + ":" + p(d.getUTCMinutes()); };

const icon = (id, c) => `<svg viewBox="0 0 24 24" style="color:${c || "currentColor"}"><use href="#i-${id}"/></svg>`;
const KIND = { chat: ["chat", "var(--upd)"], task_created: ["task", "var(--accent)"], task_updated: ["edit", "var(--accent)"], task_done: ["ok", "var(--ok)"], delegate: ["arrow", "var(--upd)"], return: ["dash", "var(--ctx)"] };
const ACT = { delegates: ["Delegates to", "arrow", "var(--upd)"], creates: ["Creates subtask", "task", "var(--accent)"], updates: ["Updates task", "edit", "var(--accent)"], completes: ["Completes task", "ok", "var(--ok)"], comments: ["Comments on task", "chat", "var(--com)"], returns: ["Sends result to", "dash", "var(--ctx)"] };
const STATUS = { created: "Created", in_progress: "In progress", review: "In review", done: "Done" };

const chip = id => `<span class="chip" style="--c:${col[id]}">${esc(ag[id].name)}</span>`;
const pill = s => `<span class="pill ${s}">${s === "done" ? icon("ok") : icon("edit")}${STATUS[s] || esc(s)}</span>`;
const taskKind = t => t.kind === "sub" ? "Subagent task" : (t.root ? "task manager item" : "task manager item, filed");
function taskCard(t, opts) {
  const o = opts || {}, who = o.who ? `<div class="who">${chip(t.agent)}<span class="mono">${esc(t.time)}</span></div>` : "";
  const c = el("div", "card", `<div class="top"><span class="id">${esc(t.id)}</span><span class="kind">${taskKind(t)}</span></div><div class="ti">${esc(t.title)}</div>${who}${pill(t.status)}`);
  c.style.setProperty("--c", col[t.agent]); c.dataset.task = t.id;
  return c;
}
const sentence = r => r.text.map(x => typeof x === "string" ? (/^#\d+$/.test(x) ? `<span class="ref">${esc(x)}</span>` : esc(x)) : chip(x.a)).join("");
const isDash = cls => cls !== "delegate";
const arrowColor = (cls, to) => cls === "context" ? "var(--ctx)" : col[to];
function marker(defs, id, color) {
  const m = svgEl("marker", { id, viewBox: "0 0 10 10", refX: 8, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  m.append(svgEl("path", { d: "M1 1L9 5L1 9z", fill: color })); defs.append(m);
}
function rpath(pts, r = 9) {
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const [a, b, c] = [pts[i - 1], pts[i], pts[i + 1]], l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
    const k = Math.min(r, l1 / 2, l2 / 2);
    d += ` L${b[0] + (a[0] - b[0]) / l1 * k} ${b[1] + (a[1] - b[1]) / l1 * k} Q${b[0]} ${b[1]} ${b[0] + (c[0] - b[0]) / l2 * k} ${b[1] + (c[1] - b[1]) / l2 * k}`;
  }
  const z = pts[pts.length - 1]; return d + ` L${z[0]} ${z[1]}`;
}
function arrow(svg, defs, id, pts, color, dash, label, extra) {
  const mid = "m-" + id; marker(defs, mid, color);
  const p = svgEl("path", { d: rpath(pts), class: "ep" + (dash ? " dash" : "") + (extra ? " " + extra : ""), style: "--c:" + color, "marker-end": `url(#${mid})` });
  const tt = svgEl("title"); tt.textContent = label || ""; p.append(tt); svg.append(p); return p;
}
function seg(label, options, current, onPick) {
  const g = el("div", "seg"); g.setAttribute("role", "group"); g.setAttribute("aria-label", label);
  if (label) g.append(el("span", "", esc(label)));
  options.forEach(([v, text]) => {
    const b = el("button", "", esc(text)); b.type = "button"; b.dataset.v = v; b.setAttribute("aria-pressed", String(v === current));
    b.onclick = () => { g.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(x === b))); onPick(v); };
    g.append(b);
  });
  return g;
}
const panelHead = (title, right) => { const h = el("div", "ph", `<h2>${esc(title)}</h2>`); if (right) h.append(right); return h; };
