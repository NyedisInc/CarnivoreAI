
'use strict';

const crypto = require('crypto');
const net = require('net');
const os = require('os');
const path = require('path');
const policy = require('./app-window-policy');

const DOOR_TIMEOUT_MS = 5000;
const MAX_REPLY_BYTES = 16384;
const CHANNEL = 'carnivore:local-login';

/* CARNIVORE_STATE_DIR CLOUDE_STATE_DIR state directory */
function defaultStateDir(env, home) {
  const named = env.CARNIVORE_STATE_DIR || env.CLOUDE_STATE_DIR;
  return named || path.join(home, 'Library', 'Application Support', 'Carnivore');
}

/* state directory */
function doorPath(stateDir, home, doorFile) {
  const h = home || os.homedir();
  if (typeof doorFile === 'string' && /^door-[0-9a-f]{8}\.sock$/.test(doorFile)) {
    return path.join(h, '.carnivore', 'fed', doorFile);
  }
  const dir = stateDir || defaultStateDir(process.env, h);
  const tag = crypto.createHash('sha256').update(dir, 'utf8').digest('hex').slice(0, 8);
  return path.join(h, '.carnivore', 'fed', `door-${tag}.sock`);
}

function doorCall(sockPath, request, opts = {}) {
  const connect = opts.connect || net.createConnection;
  const timeoutMs = opts.timeoutMs || DOOR_TIMEOUT_MS;
  return new Promise((resolve) => {
    let buf = '';
    let settled = false;
    const sock = connect({ path: sockPath });
    const done = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      sock.destroy();
      resolve(value);
    };
    const timer = setTimeout(() => done(null), timeoutMs);
    sock.on('error', () => done(null));
    sock.on('connect', () => sock.write(`${JSON.stringify(request)}\n`));
    sock.on('data', (chunk) => {
      buf += chunk.toString('utf8');
      if (buf.length > MAX_REPLY_BYTES) return done(null);
      const nl = buf.indexOf('\n');
      if (nl < 0) return undefined;
      try {
        const parsed = JSON.parse(buf.slice(0, nl));
        return done(parsed && typeof parsed === 'object' ? parsed : null);
      } catch (err) {
        return done(null);
      }
    });
    sock.on('end', () => done(null));
  });
}

/* could not be reached */
async function doorLogin(sockPath, opts) {
  const reply = await doorCall(sockPath, { op: 'login' }, opts);
  if (!reply || typeof reply.access_token !== 'string' || typeof reply.refresh_token !== 'string') return null;
  return { access_token: reply.access_token, refresh_token: reply.refresh_token, expires_in: reply.expires_in };
}

async function doorMainLabel(sockPath, opts) {
  const reply = await doorCall(sockPath, { op: 'status' }, opts);
  return reply && typeof reply.main_label === 'string' && reply.main_label ? reply.main_label : null;
}

function mayLoginLocally({ joined, fromAppWindow, senderOrigin, windowOrigin }) {
  return joined === true && fromAppWindow === true && policy.isLoopbackOrigin(senderOrigin) &&
    senderOrigin === windowOrigin;
}

function registerLocalLogin(deps) {
  const login = deps.login || doorLogin;
  deps.ipcMain.handle(CHANNEL, async (event) => {
    if (!event || !event.senderFrame || !event.sender || event.senderFrame !== event.sender.mainFrame) return null;
    const frameUrl = event.senderFrame.url;
    const allowed = mayLoginLocally({
      joined: deps.isJoined(),
      fromAppWindow: deps.isAppSender(event),
      senderOrigin: deps.originOf(frameUrl),
      windowOrigin: deps.windowOrigin(),
    });
    if (!allowed) return null;
    return login(deps.getDoorPath());
  });
}

module.exports = {
  CHANNEL, defaultStateDir, doorPath, doorCall, doorLogin, doorMainLabel,
  mayLoginLocally, registerLocalLogin,
};
