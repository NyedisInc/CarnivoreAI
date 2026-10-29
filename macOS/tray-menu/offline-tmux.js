
'use strict';

const path = require('path');
const scripts = require('../terminal-scripts');

function listSessionsArgv(socket) {
  return ['-f', '/dev/null', '-S', socket, 'list-sessions', '-F', '#{session_name}'];
}

async function readAliveCount(input) {
  const { deps } = input;
  if (!input.tmuxBin) return { alive: null, tmuxRunning: null, error: 'tmux could not be found' };
  let configText = null;
  try {
    configText = deps.fs.readFileSync(path.join(input.serverDir, 'config.json'), 'utf8');
  } catch (error) {
    configText = null;
  }
  const socket = scripts.socketPath(scripts.readSocketName(configText), deps.uid, process.env.TMUX_TMPDIR);
  if (!deps.fs.existsSync(socket)) return { alive: 0, tmuxRunning: false, error: null };
  return new Promise((resolve) => {
    deps.execFile(input.tmuxBin, listSessionsArgv(socket), { timeout: 3000 }, (error, stdout, stderr) => {
      if (error) {
        const text = String(stderr || error.message || '');
        if (/no server running|error connecting|No such file/i.test(text)) {
          resolve({ alive: 0, tmuxRunning: false, error: null });
        } else {
          resolve({ alive: null, tmuxRunning: null, error: text.trim().slice(0, 200) || 'tmux failed' });
        }
        return;
      }
      const names = String(stdout || '').split('\n').filter((n) => n.trim());
      resolve({ alive: names.length, tmuxRunning: true, error: null });
    });
  });
}

module.exports = { listSessionsArgv, readAliveCount };
