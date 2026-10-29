import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
export const repo = path.resolve(here, '..', '..');
export const macDir = path.join(repo, 'macOS');
export const menuDir = path.join(macDir, 'tray-menu');
export const load = (rel) => require(path.join(menuDir, rel));

const strings = load('strings.js');
const catalog = await import(pathToFileURL(path.join(repo, 'client/js/i18n/catalog.en.js')).href);
const format = await import(pathToFileURL(path.join(repo, 'client/js/i18n/format.js')).href);
export const t = strings.createTranslator(catalog.default, (e, p) => format.formatEntry(e, p, catalog.intlLocale));
export const catalogKeys = new Set(Object.keys(catalog.default));
export const led = load('need-you.js').loadStatusLed(path.join(repo, 'client'));
export const env = { t, led };

export function row(id, extra = {}) {
  const { at, ...wrapper } = extra;
  return {
    tmux_session: `carnivore_${id}`, label: `label ${id}`, activity_status: 'idle', unread: false,
    startup_gate: 'none', host_key: 'local', host_label: 'this mac', host_state: 'up', session_row_id: Number(id.replace(/\D/g, '')) || null,
    ...wrapper,
    session: { id: `ses_${id}`, working_dir: `/w/${id}`, last_activity: at || '2026-10-17T10:00:00Z' },
  };
}

export function snap(over = {}) {
  const ok = (data) => ({ status: 'ok', data, error: null });
  const base = {
    now: Date.parse('2026-10-17T12:00:00Z'), optionKey: false, appVersion: '1.16.1',
    server: { state: 'running', version: '1.16.1', localServerCount: 0, supervisor: { gaveUp: false, pending: false, attempts: 0, maxAttempts: 5 },
      lastExitUnexpected: false, startBlockedReason: null, portTrust: { trusted: true, reason: 'ok', holder: null, holderText: null }, portHolder: null },
    setup: 'complete', joined: false, mainLabel: null,
    update: { state: 'current', version: null, percent: 0, detail: null },
    listing: { reachable: true, live: true, rows: [], error: null },
    side: { beast: ok({ enabled: false, available: true }), swarm: ok({ enabled: false }), keepAwake: ok({ always: false }),
      logLevel: ok({ level: 'info' }), automations: { reachable: true, paused: false, total: 0, upcoming: [], recent: [] }, account: 'sam@example.com' },
    routes: { standDown: 'unknown', logLevelExpiry: 'unknown', diagnostics: 'unknown', keepAwake: 'ok' },
    offline: { alive: null, tmuxRunning: null, error: null },
    phone: { bindHost: '0.0.0.0', localIps: [{ iface: 'en0', ip: '203.0.113.12' }, { iface: 'utun4', ip: '100.64.0.2' }], effectiveHost: '0.0.0.0',
      measuredUrl: 'http://203.0.113.12:8000', publishedUrl: 'http://203.0.113.12:8000', otp: '123456', otpRemaining: 20 },
    launchAtLogin: true, offlineTuiAvailable: false, sysop: { tmuxName: 'carnivore_sysop', folder: '/p/Alpha', label: 'SysOp' },
  };
  const out = { ...base };
  for (const [k, v] of Object.entries(over)) out[k] = v && typeof v === 'object' && !Array.isArray(v) && base[k] ? { ...base[k], ...v } : v;
  return out;
}

export function walk(items, fn) {
  for (const item of items) {
    fn(item);
    if (item.submenu) walk(item.submenu, fn);
  }
}

export function byId(items, id) {
  let found;
  walk(items, (i) => { if (i.id === id) found = i; });
  return found;
}
