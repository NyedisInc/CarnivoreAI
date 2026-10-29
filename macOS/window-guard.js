'use strict';

const DOWN_ERRORS = /^net::ERR_(CONNECTION_|EMPTY_RESPONSE|SOCKET_NOT_CONNECTED)/;
const LOOPBACK_HOSTS = ['127.0.0.1', 'localhost', '[::1]'];
const DEFAULT_PORTS = { 'http:': '80', 'https:': '443', 'ws:': '80', 'wss:': '443' };

function hostKey(url) {
  try {
    const u = new URL(url);
    if (!(u.protocol in DEFAULT_PORTS)) return null;
    return `${u.hostname}:${u.port || DEFAULT_PORTS[u.protocol]}`;
  } catch (_err) {
    return null;
  }
}

function createWindowGuard({ getPort, verifyHolder, onRefused, onCleared, reloadWindows, probe = null, log = () => {} }) {
  let blocked = false;
  let checking = false;
  let generation = 0;
  let refused = false;
  let cancelledAny = false;
  let lastUptime = null;
  let held = [];
  const attached = new WeakSet();
  const origins = new Set();

  function isEngine(url) {
    const key = hostKey(url);
    if (key === null) return false;
    if (origins.has(key)) return true;
    let port;
    try { port = String(getPort()); } catch (_err) { return false; }
    return LOOPBACK_HOSTS.some((h) => key === `${h}:${port}`);
  }

  function noteDown() {
    generation += 1;
    lastUptime = null;
    if (!blocked) log('[window-guard] engine not answering, window requests to it are blocked until the holder is checked');
    blocked = true;
  }

  async function onHealth(healthy, body) {
    if (!healthy) { noteDown(); return; }
    const uptime = body && typeof body.uptime === 'number' ? body.uptime : null;
    if (!blocked && uptime !== null && lastUptime !== null && uptime < lastUptime) noteDown();
    if (uptime !== null) lastUptime = uptime;
    if (checking) return;
    const wasBlocked = blocked;
    checking = true;
    const mine = generation;
    try {
      const refusal = await verifyHolder();
      if (mine !== generation) return;
      if (refusal) {
        blocked = true;
        if (!refused) {
          log(`[window-guard] holder refused (${refusal.reason}); window requests ${wasBlocked ? 'stay' : 'are'} blocked`);
          onRefused(refusal);
        }
        refused = true;
        return;
      }
      if (!wasBlocked && !blocked) return;
      blocked = false;
      log('[window-guard] holder is ours, window requests allowed');
      const loads = held;
      held = [];
      for (const load of loads) load();
      const owed = refused || cancelledAny;
      const wasRefused = refused;
      refused = false;
      cancelledAny = false;
      if (wasRefused) onCleared();
      if (owed) reloadWindows();
    } finally {
      checking = false;
    }
  }

  function whenClear(load) {
    if (!blocked) { load(); return; }
    held.push(load);
    if (!probe) return;
    probe().then((body) => (body ? onHealth(true, body) : undefined)).catch((err) => log(`[window-guard] first check failed: ${err && err.message}`));
  }

  function attach(session, origin) {
    const key = hostKey(origin);
    if (key) origins.add(key);
    if (attached.has(session) || !session || !session.webRequest) return;
    attached.add(session);
    session.webRequest.onBeforeRequest((details, callback) => {
      const cancel = blocked && isEngine(details.url);
      if (cancel) cancelledAny = true;
      callback({ cancel });
    });
    session.webRequest.onErrorOccurred((details) => {
      if (DOWN_ERRORS.test(details.error || '') && isEngine(details.url)) noteDown();
    });
  }

  return { attach, onHealth, noteDown, whenClear, isBlocked: () => blocked };
}

module.exports = { createWindowGuard };
