
'use strict';

const trayTerminal = require('../../tray-terminal');
const { shellSingleQuote } = require('../../terminal-launcher');
const { openApp } = require('./app');

function sessionLink(a) {
  return `session/${encodeURIComponent(a.tmuxName || a.sessionId)}`;
}

async function openTerminal(ctx, row) {
  let result;
  try {
    result = await trayTerminal.openRow(row, ctx.serverManager.baseDir);
  } catch (error) {
    result = { opened: false, usedFallback: false, error: error.message };
  }
  trayTerminal.reportResult(ctx.dialog, row, result);
}

async function openSessionTerminal(ctx, a) {
  const row = { kind: 'session', tmuxName: a.tmuxName, folder: a.folder, label: a.label, displayName: a.label, readOnly: a.mode === 'watch' };
  const done = ctx.openInTerminal ? await ctx.openInTerminal.open(a.sessionId, { readOnly: row.readOnly }) : { reason: 'not_running' };
  if (done.opened || done.reason === 'cancelled') return;
  if (done.reason === 'not_running') return openTerminal(ctx, row);
  trayTerminal.reportResult(ctx.dialog, row, { opened: false, usedFallback: false, error: done.error || done.reason });
}

async function copyAttach(ctx, a) {
  const answer = ctx.openInTerminal ? await ctx.openInTerminal.attachArgv(a.sessionId) : { argv: null };
  try {
    ctx.clipboard.writeText(answer.argv ? answer.argv.map(shellSingleQuote).join(' ') : await trayTerminal.attachCommandFor(a.tmuxName, ctx.serverManager.baseDir));
  } catch (error) {
    ctx.dialog.showErrorBox('Carnivore: could not build the attach command', error.message);
  }
}

function handlers(ctx) {
  return {
    'session.open': (a) => openApp(ctx, sessionLink(a)),
    'session.attention': (a) => {
      if (a.need === 'question') {
        if (!ctx.appWindow.openApproval(a.sessionId)) openApp(ctx, sessionLink(a));
      } else {
        openApp(ctx, sessionLink(a));
      }
    },
    'session.restart': (a) => openApp(ctx, sessionLink(a)),
    'session.terminal': (a) => openSessionTerminal(ctx, a),
    'session.copy_attach': (a) => copyAttach(ctx, a),
    'terminal.sysop': () => {
      const sysop = trayTerminal.currentSysop();
      return openTerminal(ctx, { kind: 'sysop', label: trayTerminal.SYSOP_LABEL, tmuxName: sysop.tmuxName,
        folder: sysop.folder, displayName: sysop.label });
    },
    'terminal.shell': () => openTerminal(ctx, { kind: 'shell', label: ctx.t('menubar.terminal.shell') }),
    'terminal.offline': () => openTerminal(ctx, { kind: 'offline', label: ctx.t('menubar.terminal.offline') }),
  };
}

module.exports = { sessionLink, openTerminal, openSessionTerminal, copyAttach, handlers };
