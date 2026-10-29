
'use strict';

const { execFile } = require('node:child_process');

const IOREG = '/usr/sbin/ioreg';
const IOREG_ARGS = ['-n', 'Root', '-d1', '-a'];
const READ_TIMEOUT_MS = 2000;
const READ_MAX_BUFFER = 1024 * 1024;
const SCALARS = new Set(['integer', 'string', 'real', 'date', 'data']);

function readConsoleEntries(xml) {
  const at = xml.indexOf('<key>IOConsoleUsers</key>');
  if (at < 0) return null;
  const tags = [...xml.slice(at + 25).matchAll(/<(\/?)([A-Za-z]+)(\s*\/)?>([^<]*)/g)]
    .map((m) => ({ close: m[1] === '/', name: m[2], self: !!m[3], text: m[4].trim() }));
  let i = 0;
  const next = () => tags[i++] || { name: '', close: true, self: false, text: '' };
  const first = next();
  if (first.name !== 'array' || first.close || first.self) return null;
  const entries = [];
  for (;;) {
    const open = next();
    if (open.name === 'array' && open.close) return entries;
    if (open.name !== 'dict' || open.close || open.self) return null;
    const entry = new Map();
    for (;;) {
      const key = next();
      if (key.name === 'dict' && key.close) break;
      if (key.name !== 'key' || key.close || key.self) return null;
      const keyEnd = next();
      if (keyEnd.name !== 'key' || !keyEnd.close || entry.has(key.text)) return null;
      const value = next();
      if (value.close || (value.name !== 'true' && value.name !== 'false' && !value.self && !SCALARS.has(value.name))) return null;
      if (value.self) { if (value.name !== 'true' && value.name !== 'false') return null; entry.set(key.text, value.name); continue; }
      const valueEnd = next();
      if (valueEnd.name !== value.name || !valueEnd.close) return null;
      entry.set(key.text, `${value.name}:${value.text}`);
    }
    entries.push(entry);
  }
}

function parseConsoleLock(xml, uid) {
  if (typeof xml !== 'string') return null;
  const entries = readConsoleEntries(xml);
  if (!entries) return null;
  const states = [];
  for (const entry of entries) {
    if (entry.get('kCGSSessionUserIDKey') !== `integer:${uid}`) continue;
    const flag = entry.get('CGSSessionScreenIsLocked');
    if (flag !== undefined && flag !== 'true' && flag !== 'false') return null;
    states.push(flag === 'true');
  }
  if (states.length === 0 || states.some((s) => s !== states[0])) return null;
  return states[0];
}

function readOsLock(exec, uid) {
  return new Promise((resolve) => {
    try {
      exec(IOREG, IOREG_ARGS, { timeout: READ_TIMEOUT_MS, maxBuffer: READ_MAX_BUFFER, encoding: 'utf8' },
        (error, stdout) => resolve(error ? null : parseConsoleLock(String(stdout), uid)));
    } catch (_error) { resolve(null); }
  });
}

function createScreenLock(powerMonitor, opts = {}) {
  const platform = opts.platform || process.platform;
  const log = opts.log || ((line) => console.log(line));
  const tracked = !!(powerMonitor && typeof powerMonitor.on === 'function');
  const seedable = tracked && platform === 'darwin';
  let locked = seedable;
  let eventSeen = false;
  if (tracked) {
    powerMonitor.on('lock-screen', () => { eventSeen = true; locked = true; });
    powerMonitor.on('unlock-screen', () => { eventSeen = true; locked = false; });
  }
  let seeded = Promise.resolve();
  if (seedable) {
    const uid = typeof opts.uid === 'number' ? opts.uid : (typeof process.getuid === 'function' ? process.getuid() : -1);
    seeded = readOsLock(opts.exec || execFile, uid).then((state) => {
      if (eventSeen) { log('[screen-lock] start: a lock event arrived before the OS read; the event wins'); return; }
      if (state === null) { log('[screen-lock] start: OS lock read failed; assuming locked until the first unlock'); return; }
      locked = state;
      log(`[screen-lock] start: OS flag says ${state ? 'locked' : 'unlocked'}`);
    });
  }
  return { isLocked: () => locked, seeded };
}

module.exports = { createScreenLock, parseConsoleLock };
