"use strict";
(function () {
  $("#sub").textContent = `${D.title}, ${D.date}, all times ${D.tz}. ${D.agents.length} agents, ${D.tasks.length} tasks, ${D.events.length} events.`;
  $("#legend").innerHTML = [["chat", "Message / Chat", "Agent communicates", "var(--upd)"], ["task", "Task Created", "New task or item", "var(--accent)"], ["edit", "Task Updated", "Moved or changed", "var(--accent)"],
    ["ok", "Task Completed", "Task finished", "var(--ok)"], ["arrow", "Delegated", "Work handed over", "var(--upd)"], ["dash", "Callback / Result", "Result returned upstream", "var(--ctx)"]]
    .map(([i, a, b, c]) => `<div class="lg">${icon(i, c)}<div><b>${a}</b><i>${b}</i></div></div>`).join("");
  const VIEWS = { hybrid: ["Hybrid", renderHybrid, "v-hybrid"], gantt: ["Gantt", renderGantt, "v-gantt"], chat: ["Chat + Board", renderChat, "v-chat"], swim: ["Swimlanes", renderSwim, "v-swim"] };
  const made = {}; let current = null;
  function show(v) {
    current = v; Object.entries(VIEWS).forEach(([k, d]) => { $("#" + d[2]).hidden = k !== v; });
    if (!made[v]) made[v] = VIEWS[v][1]($("#" + VIEWS[v][2]));
    made[v].fit();
    try { history.replaceState(null, "", "#" + v); } catch (e) {  }
  }
  $("#vsw").replaceWith(Object.assign(seg("View", Object.entries(VIEWS).map(([k, d]) => [k, d[0]]), "hybrid", show), { id: "vsw" }));
  addEventListener("resize", () => { if (current && made[current]) made[current].fit(); });
  const want = (location.hash || "").slice(1);
  const first = VIEWS[want] ? want : "hybrid";
  show(first); $("#vsw").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === first)));
})();
