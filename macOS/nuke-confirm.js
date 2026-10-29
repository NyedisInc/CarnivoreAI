'use strict';


const RESULT_CONFIRMED = 'cloude-nuke:confirmed';
const RESULT_CANCELLED = 'cloude-nuke:cancelled';

function buildConfirmHtml(stateDirLabel) {
  const stateLine = stateDirLabel
    ? `<li>The state directory, <b>including your stored login refresh tokens</b>:<br><code>${escapeHtml(
        stateDirLabel
      )}</code></li>`
    : `<li>The state directory, <b>including your stored login refresh tokens</b>
         (path could not be determined here; nuke.sh resolves it itself and
         refuses to run if it cannot)</li>`;

  const body = `<p>This permanently removes, with no undo:</p>
  <ul>
    <li>All local configuration (<code>.env</code>, <code>config.json</code>)</li>
    <li>The Python virtual environment</li>
    ${stateLine}
    <li>The session database and migration trail</li>
    <li>All logs, temporary files, macOS app settings and the LaunchAgent</li>
  </ul>`;
  return buildTypedPage({ heading: 'Complete System Reset', body, word: 'NUKE', goLabel: 'Nuke it from Orbit' });
}

function buildUninstallHtml() {
  const body = `<p>This removes carnivore from this computer, with no undo:</p>
  <ul>
    <li>The app, <code>/Applications/Carnivore.app</code></li>
    <li>Its settings, state and session database</li>
    <li>Its keychain items</li>
    <li><b>Every running carnivore session ends</b>, and work inside them stops</li>
  </ul>
  <p>These stay: <code>~/carnivore-projects</code>, <code>~/.claude</code>, <code>~/.carnivore</code>, and your
    Claude Code and Codex logins.</p>`;
  return buildTypedPage({ heading: 'Uninstall Carnivore', body, word: 'UNINSTALL', goLabel: 'Uninstall Carnivore' });
}

function buildTypedPage(spec) {
  const { heading, body, word, goLabel } = spec;
  return `<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body { margin:0; padding:28px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
         background:#1a1a1a; color:#eee; font-size:13px; }
  h1 { font-size:17px; margin:0 0 12px; color:#ff6b6b; }
  ul { margin:0 0 16px 18px; padding:0; line-height:1.55; }
  code { background:#000; padding:1px 4px; border-radius:3px; font-size:11px; word-break:break-all; }
  p.ask { margin:16px 0 8px; }
  input { width:100%; box-sizing:border-box; padding:9px 10px; font-size:15px; font-family:monospace;
          letter-spacing:2px; background:#000; color:#fff; border:1px solid #555; border-radius:5px; }
  input:focus { outline:none; border-color:#ff6b6b; }
  .row { display:flex; gap:10px; justify-content:flex-end; margin-top:18px; }
  button { padding:8px 18px; font-size:13px; border-radius:6px; border:1px solid #555;
           background:#2d2d2d; color:#eee; cursor:pointer; }
  button#go { background:#7a1f1f; border-color:#a33; }
  button#go:disabled { background:#2d2d2d; border-color:#444; color:#666; cursor:not-allowed; }
</style></head>
<body>
  <h1>${heading}</h1>
  ${body}
  <p class="ask">Type <b>${word}</b> to confirm:</p>
  <input id="word" autocomplete="off" autocorrect="off" spellcheck="false">
  <div class="row">
    <button id="cancel">Cancel</button>
    <button id="go" disabled>${goLabel}</button>
  </div>
<script>
  var input = document.getElementById('word');
  var go = document.getElementById('go');
  var cancel = document.getElementById('cancel');
  function cancelled() { document.title = ${JSON.stringify(RESULT_CANCELLED)}; }
  input.addEventListener('input', function () { go.disabled = input.value !== ${JSON.stringify(word)}; });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && input.value === ${JSON.stringify(word)}) { document.title = ${JSON.stringify(
      RESULT_CONFIRMED
    )}; }
    if (e.key === 'Escape') { cancelled(); }
  });
  go.addEventListener('click', function () {
    if (input.value === ${JSON.stringify(word)}) { document.title = ${JSON.stringify(RESULT_CONFIRMED)}; }
  });
  cancel.addEventListener('click', cancelled);
  input.focus();
</script>
</body></html>`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function promptForTypedConfirmation(page) {
  const { BrowserWindow } = require('electron');
  return new Promise((resolve) => {
    const win = new BrowserWindow({
      width: 520,
      height: page.height,
      resizable: false,
      minimizable: false,
      maximizable: false,
      fullscreenable: false,
      show: false,
      backgroundColor: '#1a1a1a',
      title: page.title,
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true }
    });

    let settled = false;
    const finish = (verdict) => {
      if (settled) return;
      settled = true;
      resolve(verdict);
      if (!win.isDestroyed()) win.close();
    };

    win.webContents.on('page-title-updated', (event, title) => {
      event.preventDefault();
      if (title === RESULT_CONFIRMED) finish(true);
      else if (title === RESULT_CANCELLED) finish(false);
    });
    win.on('closed', () => finish(false));

    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(page.html));
    win.once('ready-to-show', () => win.show());
  });
}

function promptForNukeConfirmation(stateDirLabel) {
  return promptForTypedConfirmation({ title: 'Complete System Reset', html: buildConfirmHtml(stateDirLabel), height: 470 });
}

function promptForUninstallConfirmation() {
  return promptForTypedConfirmation({ title: 'Uninstall Carnivore', html: buildUninstallHtml(), height: 440 });
}

module.exports = {
  promptForNukeConfirmation,
  promptForUninstallConfirmation,
  buildConfirmHtml,
  buildUninstallHtml,
  RESULT_CONFIRMED,
  RESULT_CANCELLED
};
