
'use strict';

const path = require('path');
const terminalLauncher = require('../../terminal-launcher');
const { openWindowAfterStart } = require('./open-after-start');

function openInConfiguredEditor(ctx, filePath) {
  let editor = null;
  try {
    const parsed = JSON.parse(ctx.fs.readFileSync(ctx.serverManager.getConfigPath(), 'utf8'));
    const configured = parsed && parsed.workspace && parsed.workspace.default_editor;
    if (typeof configured === 'string' && configured.trim()) editor = configured.trim();
  } catch (err) {
    console.warn('[edit-config] could not read default_editor:', err.message);
  }
  const note = {
    type: 'info', title: 'Edit config', message: 'Restart the server after you save.',
    detail: 'The running server parsed this file at startup and caches it, so a hand edit does not take effect until '
      + 'it restarts. Changes made from the web app\'s settings screen apply without one.',
    buttons: ['OK'],
  };
  if (!editor) {
    ctx.shell.openPath(filePath).then((err) => {
      if (err) ctx.dialog.showErrorBox('Carnivore: could not open config', `macOS could not open ${filePath}: ${err}`);
      else ctx.dialog.showMessageBox(note);
    });
    return;
  }
  ctx.exec(`${editor} ${JSON.stringify(filePath)}`, (err) => {
    if (err) {
      ctx.dialog.showErrorBox('Carnivore: editor would not launch',
        `The configured editor could not open the file.\n\nCommand: ${editor}\nFile: ${filePath}\n\n${err.message}\n\n`
        + 'Change "default editor" on the settings screen, or clear it to use the system default.');
      return;
    }
    ctx.dialog.showMessageBox(note);
  });
}

function tailServerLog(ctx) {
  const logPath = ctx.serverManager.logFile;
  if (!ctx.fs.existsSync(logPath)) {
    ctx.dialog.showMessageBox({ type: 'info', title: 'Logs Not Available', message: 'Server logs not available',
      detail: 'The server was already running when the app started, so logs were not captured. Restart the server from the app to enable log capture.' });
    return;
  }
  const scriptPath = path.join(path.dirname(logPath), terminalLauncher.DEFAULT_SCRIPT_BASENAME);
  terminalLauncher.openServerLogInDefaultTerminal(logPath, scriptPath, (result) => {
    if (!result.opened) {
      ctx.dialog.showErrorBox('Carnivore: could not open the log', 'The server log could not be opened in a terminal.\n\n'
        + String((result.error && result.error.message) || result.error || '') + '\n\nThe log file itself is at:\n' + logPath);
    } else if (result.usedFallback) {
      ctx.dialog.showMessageBox({ type: 'info', title: 'Opened in Terminal', message: 'Opened the log in Terminal',
        detail: 'No default handler for .command files could be determined, so Terminal was used instead of your default terminal app.' });
    }
  }, { fs: ctx.fs, shell: ctx.shell, execFile: ctx.execFile });
}

function handlers(ctx) {
  const sm = ctx.serverManager;
  return {
    'server.restart': async () => {
      try {
        const result = await sm.restart();
        if (result && result.refused) await ctx.offerTakeOwnership('restart', result);
      } catch (err) {
        ctx.dialog.showErrorBox('Carnivore could not restart the server', err.message);
      }
      ctx.refresh();
    },
    'server.stop': async () => {
      try {
        const result = await sm.stop();
        if (result && result.refused) await ctx.offerTakeOwnership('stop', result);
      } catch (err) {
        await ctx.reportStartFailure(err);
      }
      ctx.refresh();
    },
    'server.stop_retry': () => { sm.cancelSlowRetry(); ctx.refresh(); },
    'server.start': async () => {
      try {
        sm.resetSupervisor();
        await sm.start();
        ctx.refresh();
        await openWindowAfterStart(ctx);
      } catch (err) {
        await ctx.reportStartFailure(err);
      }
      ctx.refresh();
    },
    'server.toggle_login': () => {
      ctx.launchAgentInstaller.toggle(ctx.launchArgs());
      ctx.refresh();
    },
    'server.supervisor_why': (a) => ctx.dialog.showMessageBox({ type: a.gaveUp ? 'warning' : 'info',
      title: 'Automatic server restart', message: a.label, detail: a.detail, buttons: ['OK'] }),
    'server.why': (a) => ctx.dialog.showMessageBox({ type: 'info', title: 'Why the server is stopped',
      message: 'The Carnivore server is not running.', detail: a.detail, buttons: ['OK'] }),
    'server.edit_config': () => openInConfiguredEditor(ctx, path.join(sm.getProjectRoot(), 'config.json')),
    'server.tail_log': () => tailServerLog(ctx),
  };
}

module.exports = { openInConfiguredEditor, tailServerLog, handlers };
