'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');

const MARKER_NAME = '.carnivore-proof-marker.json';
const LOG_NAME = 'marker-applied.log';
const KEYS = ['home', 'user_data', 'state', 'tmux', 'tmp', 'settings_env', 'port', 'host'];
const PATH_KEYS = ['home', 'user_data', 'state', 'tmux', 'tmp', 'settings_env'];
const PURPOSE_KEY = 'CarnivoreBuildPurpose';
const PROOF_PURPOSE = 'update-proof';

function readBuildPurpose(bundle) {
  try {
    const xml = fs.readFileSync(path.join(bundle, 'Contents', 'Info.plist'), 'utf8');
    const m = new RegExp('<key>' + PURPOSE_KEY + '</key>\\s*<string>([^<]*)</string>').exec(xml);
    return m ? m[1] : null;
  } catch (e) {
    return null;
  }
}

function bundleOf(exePath = process.execPath) {
  const bundle = path.resolve(exePath, '..', '..', '..');
  return bundle.endsWith('.app') ? bundle : null;
}

function readRunningPurpose(exePath = process.execPath) {
  const bundle = bundleOf(exePath);
  return bundle === null ? null : readBuildPurpose(bundle);
}

function realOrNull(p) {
  try { return fs.realpathSync(p); } catch (e) { return null; }
}

function within(root, child) {
  const rel = path.relative(root, child);
  return rel === '' || (!rel.startsWith('..') && !path.isAbsolute(rel));
}

function defaultRoots() {
  const out = [os.tmpdir(), '/tmp', '/private/tmp', '/private/var/folders'];
  return out.map(realOrNull).filter(Boolean);
}

function validate(markerPath, uid, roots) {
  let fd;
  try {
    fd = fs.openSync(markerPath, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  } catch (e) { if (e.code === 'ENOENT') return { absent: true }; return { reason: 'open ' + e.code }; }
  let data;
  try {
    const st = fs.fstatSync(fd);
    if (!st.isFile()) return { reason: 'not a regular file' };
    if (st.uid !== uid) return { reason: 'owner is not the current user' };
    if (st.mode & 0o022) return { reason: 'group or world writable' };
    try { data = JSON.parse(fs.readFileSync(fd, 'utf8')); } catch (e) { return { reason: 'not valid json' }; }
  } finally {
    fs.closeSync(fd);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) return { reason: 'not an object' };
  const keys = Object.keys(data).sort();
  if (keys.join() !== KEYS.slice().sort().join()) return { reason: 'unexpected or missing keys' };
  if (!Number.isInteger(data.port) || data.port < 1024 || data.port > 65535) return { reason: 'bad port' };
  if (data.host !== '127.0.0.1') return { reason: 'bad host' };
  const base = realOrNull(path.dirname(path.dirname(markerPath)));
  if (!base || !roots.some((r) => within(r, base))) return { reason: 'evidence folder outside allowed roots' };
  for (const k of PATH_KEYS) {
    const v = data[k];
    if (typeof v !== 'string' || !path.isAbsolute(v) || v.split(path.sep).includes('..')) return { reason: 'bad path ' + k };
    try { if (fs.lstatSync(v).isSymbolicLink()) return { reason: 'path is a symlink: ' + k }; } catch (e) {  }
    const whole = realOrNull(v);
    const parent = realOrNull(path.dirname(v));
    const real = whole || (parent ? path.join(parent, path.basename(v)) : path.resolve(v));
    if (!within(base, real) || real === base) return { reason: 'path outside evidence folder: ' + k };
  }
  return { data };
}

function logLine(dir, outcome, now) {
  try {
    fs.appendFileSync(path.join(dir, LOG_NAME), process.pid + ' ' + now().toISOString() + ' ' + outcome + '\n');
  } catch (e) {
  }
}

function applyProofMarker(app, opts = {}) {
  try {
    return applyChecked(app, opts);
  } catch (e) {
    return { applied: false, reason: 'error ' + ((e && e.code) || 'unknown') };
  }
}

function applyChecked(app, { env = process.env, exePath = process.execPath, uid = process.getuid(), roots = defaultRoots(), now = () => new Date() } = {}) {
  const bundle = bundleOf(exePath);
  if (bundle === null) return { applied: false, reason: null };
  if (readBuildPurpose(bundle) !== PROOF_PURPOSE) return { applied: false, reason: null };
  const dir = path.dirname(bundle);
  const v = validate(path.join(dir, MARKER_NAME), uid, roots);
  if (v.absent) return { applied: false, reason: null };
  if (v.reason) { logLine(dir, 'refused: ' + v.reason, now); return { applied: false, reason: v.reason }; }
  const d = v.data;
  env.HOME = d.home;
  env.CFFIXED_USER_HOME = d.home;
  env.TMUX_TMPDIR = d.tmux;
  env.TMPDIR = d.tmp;
  env.CARNIVORE_STATE_DIR = d.state;
  env.CARNIVORE_SETTINGS_ENV_FILE = d.settings_env;
  env.CARNIVORE_LEDGER_KEEPALIVE = '0';
  env.PORT = String(d.port);
  env.HOST = d.host;
  app.setPath('home', d.home);
  app.setPath('userData', d.user_data);
  app.commandLine.appendSwitch('user-data-dir', d.user_data);
  app.commandLine.appendSwitch('use-mock-keychain');
  logLine(dir, 'applied', now);
  return { applied: true, reason: null };
}

module.exports = { applyProofMarker, readBuildPurpose, readRunningPurpose, bundleOf, PROOF_PURPOSE, MARKER_NAME, LOG_NAME };
