"use strict";
function renderChat(root) {
  const cols = el("div", "ch-cols"), links = svgEl("svg", { id: "ch-links" }); cols.append(links);
  const depthOf = id => { let d = 0, p = ag[id].parent; while (p && d < 3) { d++; p = ag[p].parent; } return d; };
  const left = el("section", "panel"), thread = el("div", "ch-thread"), msgs = [];
  const fold = seg("", [["open", "Expand all"], ["closed", "Collapse all"]], "open", v => msgs.forEach(m => m.classList.toggle("shut", v === "closed")));
  fold.setAttribute("aria-label", "Threads");
  left.append(panelHead("Threaded Conversation", fold), thread);
  const actHtml = a => {
    const [label0, ic, color] = ACT[a.a], t = a.task && taskById[a.task], label = a.a === "creates" && a.root ? "Creates task" : label0;
    const who = a.to ? chip(a.to) : "", ref = t ? `<span class="ref">${esc(t.id)}</span><span class="tt">${esc(t.title)}</span>` : "";
    return `<span class="act">${icon(ic, color)}<span>${label}</span>${who}${ref}</span>`;
  };
  D.events.forEach(r => {
    const who = r.from, m = el("div", "msg", `<div class="av sm">${esc(ag[who].mono)}</div><div class="bub"><div class="mh"><b>${esc(ag[who].name)}</b><span class="tm mono">${esc(r.time)}</span></div>` +
      `<div class="tx">${esc(r.quote || (r.kind === "return" ? "Returned its result." : ""))}</div><div class="acts">${r.acts.map(actHtml).join("")}</div></div>`);
    m.style.cssText = `--c:${col[who]};--ind:${depthOf(who) * 18}px`; m.dataset.ev = r.id;
    if (!m.querySelector(".tx").textContent) m.querySelector(".tx").remove();
    m.querySelector(".bub").onclick = () => m.classList.toggle("shut");
    msgs.push(m); thread.append(m);
  });
  const right = el("section", "panel"), body = el("div"); let mode = "board";
  const sw = seg("", [["board", "Board"], ["list", "List"]], "board", v => { mode = v; draw(); });
  sw.setAttribute("aria-label", "Task view");
  right.append(panelHead("Task Board", sw), body);
  const cards = {};
  function draw() {
    body.innerHTML = ""; links.replaceChildren();
    if (mode === "board") {
      const g = el("div", "bd-cols");
      Object.keys(STATUS).forEach(s => { const list = D.tasks.filter(t => t.status === s), c = el("div", "bd-col", `<h3><span>${STATUS[s]}</span><i>${list.length}</i></h3>`);
        list.forEach(t => { const cd = taskCard(t, { who: true }); cd.insertAdjacentHTML("afterbegin", '<span class="port"></span>'); c.append(cd); cards[t.id] = cd; }); g.append(c); });
      body.append(g);
    } else {
      const rows = D.tasks.map(t => `<tr><td><span class="ref">${esc(t.id)}</span></td><td>${esc(t.title)}</td><td>${chip(t.agent)}</td><td>${pill(t.status)}</td><td class="mono">${esc(t.time)}</td></tr>`).join("");
      body.append(el("div", "bd-listwrap", `<table class="bd-list"><thead><tr><th>Task</th><th>Title</th><th>Agent</th><th>Status</th><th>Created</th></tr></thead><tbody>${rows}</tbody></table>`));
    }
    if (D.final) body.append(el("div", "cb", `${icon("dash")}<b>Callback / Result</b><span class="sp">${esc(D.final.text)}</span><span>Sent to ${chip(D.agents.find(a => a.kind === "owner") ? D.agents.find(a => a.kind === "owner").id : rootId)}</span><span class="mono">${esc(D.final.time)}</span>`));
    msgs.forEach(m => m.querySelector(".port") && m.querySelector(".port").remove());
    if (mode === "board") D.events.forEach((r, i) => { const t = r.acts.map(a => a.task).find(x => x && cards[x]); if (t && !cards[t]._linked) { cards[t]._linked = i; msgs[i].querySelector(".bub").insertAdjacentHTML("beforeend", '<span class="port"></span>'); } });
  }
  function connect(m, on) {
    links.replaceChildren(); document.querySelectorAll("#v-chat .on").forEach(x => x.classList.remove("on"));
    if (!on || mode !== "board" || getComputedStyle(links).display === "none") return;
    const r = D.events.find(e => e.id === m.dataset.ev), base = cols.getBoundingClientRect(); m.classList.add("on");
    r.acts.map(a => a.task).filter(x => x && cards[x]).forEach(id => {
      const a = m.querySelector(".bub").getBoundingClientRect(), b = cards[id].getBoundingClientRect(); cards[id].classList.add("on");
      if (b.left < a.right + 20) return;
      const x1 = a.right - base.left, y1 = a.top + 14 - base.top, x2 = b.left - base.left, y2 = b.top + 14 - base.top, mx = (x1 + x2) / 2;
      const p = svgEl("path", { d: `M${x1} ${y1} C${mx} ${y1} ${mx} ${y2} ${x2} ${y2}`, style: "--c:" + col[taskById[id].agent] }); links.append(p);
    });
  }
  msgs.forEach(m => { m.onmouseenter = () => connect(m, true); m.onmouseleave = () => connect(m, false); });
  cols.append(left, right); root.append(cols); draw();
  const fit = () => { const w = cols.offsetWidth, h = cols.offsetHeight; links.setAttribute("width", w); links.setAttribute("height", h); links.style.display = w < 1100 ? "none" : ""; };
  return { fit };
}
