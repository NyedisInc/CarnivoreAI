'use strict';

const fs = require('fs');
const path = require('path');

const GUARD_FILE = 'engine-service-restarts.json';
const MAX_RESTARTS = 3;
const MAX_VERSIONS = 8;
const WINDOW_MS = 10 * 60 * 1000;

function parseBundleVersion(text) {
  const match = /<key>CFBundleShortVersionString<\/key>\s*<string>([^<]+)<\/string>/.exec(String(text));
  return match ? match[1].trim() : null;
}

function readDiskVersion({ exe, fsImpl = fs }) {
  try {
    return parseBundleVersion(fsImpl.readFileSync(path.resolve(exe, '..', '..', 'Info.plist'), 'utf8'));
  } catch (err) {
    return null;
  }
}

function createRestartGuard({ userData, file: name = GUARD_FILE, fsImpl = fs, now = () => Date.now(), max = MAX_RESTARTS, windowMs = WINDOW_MS }) {
  const file = path.join(userData, name);
  const read = () => {
    try {
      const raw = JSON.parse(fsImpl.readFileSync(file, 'utf8'));
      return raw && typeof raw === 'object' && raw.entries && typeof raw.entries === 'object' ? Object.assign(Object.create(null), raw.entries) : Object.create(null);
    } catch (err) {
      return Object.create(null);
    }
  };
  const fresh = (rec) => {
    const age = now() - Number(rec && rec.firstAt);
    return age >= 0 && age < windowMs;
  };
  const live = (entries, disk) => (Object.hasOwn(entries, disk) && fresh(entries[disk]) ? entries[disk] : { count: 0, firstAt: now() });
  return {
    allow: (disk) => live(read(), String(disk)).count < max,
    record(disk) {
      const key = String(disk);
      const entries = read();
      const rec = live(entries, key);
      rec.count += 1;
      entries[key] = rec;
      const kept = Object.entries(entries).filter(([, r]) => fresh(r)).sort((x, y) => y[1].firstAt - x[1].firstAt).slice(0, MAX_VERSIONS);
      fsImpl.mkdirSync(userData, { recursive: true });
      fsImpl.writeFileSync(file, `${JSON.stringify({ entries: Object.fromEntries(kept) })}\n`, { mode: 0o600 });
      return rec.count;
    },
    clear() {
      try {
        fsImpl.unlinkSync(file);
      } catch (err) {
        if (err.code !== 'ENOENT') throw err;
      }
    },
  };
}

function decideVersionAction({ running, disk, guard }) {
  if (!disk || disk === running) return 'ok';
  return guard.allow(disk) ? 'restart' : 'hold';
}

module.exports = { GUARD_FILE, MAX_RESTARTS, WINDOW_MS, parseBundleVersion, readDiskVersion, createRestartGuard, decideVersionAction };
