
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');
const scripts = require('./terminal-scripts');
const terminalOpen = require('./terminal-open');
const { pycacheEnv } = require('./engine/payload-select');

const SYSOP_LABEL = 'SysOp';
const SYSOP_RANK = 'alpha';
const LOCAL_HOST_KEY = 'local';

let lastSysop = { tmuxName: null, folder: null, label: SYSOP_LABEL };

async function refreshSysop(trayApi) {
  const result = await trayApi.getAuthed('/api/v1/swarm/roster');
  if (!result.reachable || !result.data || !Array.isArray(result.data.agents)) return lastSysop;
  const agent = result.data.agents.find(
    (a) => a && a.rank === SYSOP_RANK && (a.host_key || LOCAL_HOST_KEY) === LOCAL_HOST_KEY
  );
  lastSysop = {
    tmuxName: agent && scripts.isValidTmuxName(agent.tmux_session) ? agent.tmux_session : null,
    folder: agent && scripts.isAbsolutePath(agent.repo_dir) ? agent.repo_dir : null,
    label: (agent && typeof agent.display_name === 'string' && agent.display_name) || SYSOP_LABEL,
  };
  return lastSysop;
}

function currentSysop() {
  return lastSysop;
}

function readTextOrNull(file) {
  try {
    return fs.readFileSync(file, 'utf8');
  } catch (error) {
    if (error.code !== 'ENOENT') console.warn('[tray-terminal] could not read', file, error.message);
    return null;
  }
}

function offlineTuiAvailable(serverDir, payload) {
  return fs.existsSync(path.join(serverDir, 'src', 'tui', 'offline', 'launch.py'))
    && fs.existsSync(payload ? payload.python : path.join(serverDir, 'venv', 'bin', 'python3'));
}

function serverSocketPath(serverDir, uid) {
  const socketName = scripts.readSocketName(readTextOrNull(path.join(serverDir, 'config.json')));
  return scripts.socketPath(socketName, uid, process.env.TMUX_TMPDIR);
}

async function attachCommandFor(tmuxName, serverDir) {
  const deps = terminalOpen.liveDeps();
  const socketPath = serverSocketPath(serverDir, deps.uid);
  const tools = await terminalOpen.resolveTools(deps, socketPath);
  return scripts.attachCommand({ tmuxBin: tools.tmux, socketPath, tmuxName });
}

async function openRow(row, serverDir) {
  const deps = terminalOpen.liveDeps();
  const home = os.homedir();
  let contents;
  let basename;
  try {
    if (row.kind === 'shell') {
      contents = scripts.buildShellScript({ folder: home, shellBin: terminalOpen.loginShell(deps) });
      basename = 'carnivore-shell.command';
    } else if (row.kind === 'offline') {
      contents = scripts.buildOfflineTuiScript({ serverDir, payload: deps.payload, pycache: deps.payload ? pycacheEnv() : undefined });
      basename = 'carnivore-offline-sessions.command';
    } else {
      const socketPath = serverSocketPath(serverDir, deps.uid);
      const tools = await terminalOpen.resolveTools(deps, socketPath);
      const folder = row.kind === 'sysop' || !scripts.isAbsolutePath(row.folder) ? home : row.folder;
      contents = scripts.buildSessionScript({
        tmuxBin: tools.tmux,
        socketPath,
        readOnly: Boolean(row.readOnly),
        tmuxName: row.tmuxName || null,
        folder,
        homeFolder: home,
        shellBin: terminalOpen.loginShell(deps),
        claudeBin: tools.claude,
        label: row.displayName || row.label,
      });
      basename = 'carnivore-session.command';
    }
  } catch (error) {
    return { opened: false, usedFallback: false, error: error.message };
  }
  return terminalOpen.openScriptInTerminal(contents, basename, deps);
}

function reportResult(dialog, row, result) {
  if (!result.opened) {
    dialog.showErrorBox('Carnivore: could not open a terminal', `${row.label}: ${result.error || 'unknown error'}`);
    return;
  }
  if (result.usedFallback) {
    dialog.showMessageBox({
      type: 'info',
      title: 'Opened in Terminal',
      message: 'Opened in Terminal',
      detail: 'Your default app for .command files is not a terminal Carnivore knows, or could not be determined, '
        + 'so Terminal was used instead.',
    });
  }
}

function sweepAtStartup() {
  return terminalOpen.sweepStaleScripts(terminalOpen.liveDeps());
}

module.exports = {
  SYSOP_LABEL,
  refreshSysop,
  currentSysop,
  offlineTuiAvailable,
  serverSocketPath,
  attachCommandFor,
  openRow,
  reportResult,
  sweepAtStartup,
};
