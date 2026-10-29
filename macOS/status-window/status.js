
'use strict';

(function () {
  const CONFIRM_ID = 'server.start';
  const api = window.carnivoreStatus;
  const $ = (id) => document.getElementById(id);

  function render(facts) {
    if (!facts) return;
    document.title = facts.windowTitle;
    $('sw-title').textContent = facts.title;
    $('sw-name').textContent = facts.windowTitle;
    $('sw-status').textContent = facts.status;
    const why = $('sw-why');
    why.hidden = !facts.why.text;
    why.textContent = facts.why.text;
    why.title = facts.why.hint;
    why.disabled = !facts.why.enabled;
    why.onclick = () => api.runAction('server.why');
    const actions = $('sw-actions');
    actions.replaceChildren();
    facts.buttons.forEach((button) => {
      const row = document.createElement('div');
      row.className = 'sw-row';
      const el = document.createElement('button');
      el.type = 'button';
      el.className = button.id === CONFIRM_ID ? 'sw-btn sw-btn--confirm' : 'sw-btn';
      el.textContent = button.label;
      el.disabled = !button.enabled;
      el.onclick = () => api.runAction(button.id);
      row.appendChild(el);
      if (button.reason) {
        const note = document.createElement('p');
        note.className = 'sw-reason';
        note.textContent = button.reason;
        row.appendChild(note);
      }
      actions.appendChild(row);
    });
  }

  api.onFacts(render);
  api.requestFacts().then(render);
})();
