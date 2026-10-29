
'use strict';

(function () {
  const api = window.carnivoreUpdate;
  const $ = (id) => document.getElementById(id);

  function render(facts) {
    if (!facts) return;
    document.title = facts.title;
    $('uw-title').textContent = facts.title;
    $('uw-name').textContent = facts.name;
    $('uw-status').textContent = facts.status;
    $('uw-bar').hidden = facts.percent === null;
    $('uw-fill').style.width = `${facts.percent || 0}%`;
    $('uw-detail').hidden = !facts.detail;
    $('uw-detail').textContent = facts.detail;
    const retry = $('uw-retry');
    retry.hidden = !facts.retryLabel;
    retry.textContent = facts.retryLabel || '';
    retry.onclick = () => api.runAction('update.install');
  }

  api.onFacts(render);
  api.requestFacts().then(render);
})();
