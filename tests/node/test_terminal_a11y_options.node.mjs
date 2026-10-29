import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (p) => fs.readFileSync(path.join(root, p), 'utf8');
const src = read('client/js/terminal-screen-reader.js');

function world(shared, desktop) {
  const store = new Map();
  const subs = [];
  const listeners = [];
  const bridge = {
    value: shared,
    read(field, local) { return this.value === undefined ? local() : this.value; },
    follow(field, fn) { subs.push([field, fn]); return () => {}; },
  };
  const sandbox = {
    console, WeakRef, Set, Map, Promise,
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.location = { origin: 'http://127.0.0.1:5001' };
  sandbox.addEventListener = (type, fn) => listeners.push([type, fn]);
  sandbox.PreferenceBridge = bridge;
  if (desktop) sandbox.carnivoreDesktop = desktop;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  const push = (value) => subs.filter(([f]) => f === 'terminal_screen_reader').forEach(([, fn]) => fn(value));
  const inner = vm.runInContext('window', sandbox);
  const post = (data, source = inner, origin = 'http://127.0.0.1:5001') =>
    listeners.filter(([type]) => type === 'message').forEach(([, fn]) => fn({ data, source, origin }));
  return { mod: sandbox.TerminalScreenReader, bridge, push, post, store, inner };
}
const term = () => ({ options: { screenReaderMode: false } });
const tick = () => new Promise((r) => setImmediate(r));

let n = 0;
/** Run one named case. */
async function t(name, fn) { await fn(); n++; console.log(`ok - ${name}`); }

await t('the options builder: auto follows the OS signal, on and off are forced both ways', () => {
  const { mod } = world(undefined);
  assert.equal(mod.optionsFor('auto', true).screenReaderMode, true);
  assert.equal(mod.optionsFor('auto', false).screenReaderMode, false);
  assert.equal(mod.modeFor('on', false), true, 'forced on wins with no OS signal');
  assert.equal(mod.modeFor('on', true), true);
  assert.equal(mod.modeFor('off', true), false, 'forced off wins over the OS signal');
  assert.equal(mod.modeFor('off', false), false);
  for (const odd of [undefined, null, '', 'loud', true, 1]) assert.equal(mod.modeFor(odd, true), true, `${String(odd)} reads as auto`);
});

await t('a terminal opened before the toggle follows the setting and the OS signal live, with no reload', () => {
  const w = world(undefined);
  const a = term(); const b = term();
  w.mod.bind(a); w.mod.bind(b);
  assert.equal(a.options.screenReaderMode, false, 'auto, no OS signal: off');
  w.mod.setOsSignal(true);
  assert.equal(a.options.screenReaderMode, true); assert.equal(b.options.screenReaderMode, true);
  w.push('off');
  assert.equal(a.options.screenReaderMode, false, 'forced off beats the OS signal on an open terminal');
  w.push('on'); w.mod.setOsSignal(false);
  assert.equal(b.options.screenReaderMode, true, 'forced on holds with no OS signal');
  w.push(null);
  assert.equal(a.options.screenReaderMode, false, 'a field returned to its default is auto, and the OS signal is off');
});

await t('a terminal bound later starts from the saved setting; a reconnect re-read repaints', () => {
  const w = world('on');
  const a = term(); w.mod.bind(a);
  assert.equal(a.options.screenReaderMode, true);
  w.bridge.value = 'off';
  assert.equal(w.mod.apply(), false); assert.equal(a.options.screenReaderMode, false);
  assert.equal(w.store.get('carnivore.terminal-screen-reader'), 'off', 'a paint-fast local copy is kept');
});

await t('the desktop app: the shell reports the OS signal at load and on each change', async () => {
  const desktop = Object.freeze({ capabilities: Object.freeze(['screenReader']), screenReader: () => Promise.resolve(true) });
  const w = world(undefined, desktop);
  const a = term(); w.mod.bind(a);
  await tick();
  assert.equal(a.options.screenReaderMode, true, 'VoiceOver already running at load');
  w.post({ type: 'carnivore.screen-reader', on: false });
  assert.equal(a.options.screenReaderMode, false);
  w.post({ type: 'carnivore.screen-reader', on: true });
  assert.equal(a.options.screenReaderMode, true);
  w.post({ type: 'carnivore.screen-reader', on: 'yes' }); w.post({ type: 'other', on: false });
  w.post({ type: 'carnivore.screen-reader', on: false }, {}, 'http://127.0.0.1:5001');
  w.post({ type: 'carnivore.screen-reader', on: false }, w.inner, 'https://evil.example');
  assert.equal(a.options.screenReaderMode, true, 'a non boolean, another type, another source or another origin is ignored');
});

await t('a plain browser tab or a shell without the capability has no OS signal and uses the setting alone', async () => {
  const browser = world(undefined);
  const a = term(); browser.mod.bind(a);
  assert.equal(a.options.screenReaderMode, false);
  browser.push('on'); assert.equal(a.options.screenReaderMode, true);
  let asked = 0;
  const old = world(undefined, { capabilities: ['notify'], screenReader: () => { asked++; return Promise.resolve(true); } });
  const b = term(); old.mod.bind(b); await tick();
  assert.equal(asked, 0); assert.equal(b.options.screenReaderMode, false);
});

await t('html lang follows the locale at boot and on a change; the static labels come from the catalog', async () => {
  const { bindDocumentLang, langOf, STATIC_LABELS } = await import(pathToFileURL(path.join(root, 'client/js/i18n/document-lang.js')).href);
  const { CATALOGS } = await import(pathToFileURL(path.join(root, 'client/js/i18n/catalogs.js')).href);
  assert.equal(langOf('en'), 'en'); assert.equal(langOf('pseudo'), 'en'); assert.equal(langOf('nope'), 'en');
  const attrs = {}; const labels = {};
  const doc = {
    documentElement: { setAttribute: (k, v) => { attrs[k] = v; } },
    querySelector: (sel) => ({ setAttribute: (k, v) => { labels[sel] = v; } }),
  };
  let listener = null; let locale = 'pseudo';
  const i18n = { get locale() { return locale; }, t: (k) => `<${k}>`, onLocaleChange: (fn) => { listener = fn; return () => {}; } };
  bindDocumentLang(i18n, doc);
  assert.equal(attrs.lang, 'en');
  assert.equal(labels['#session-sidebar-list'], '<a11y.session_list>');
  CATALOGS.xx = { messages: {}, intl: 'de-DE' }; locale = 'xx'; listener('xx');
  assert.equal(attrs.lang, 'de-DE', 'a locale change rewrites lang');
  delete CATALOGS.xx;
  for (const [, key] of STATIC_LABELS) assert.ok(CATALOGS.en.messages[key], `catalog has ${key}`);
});

await t('the wiring: boot sets lang, terminals bind, the preload lists the capability at contract 1, the field is typed', () => {
  assert.match(read('client/js/i18n/boot.js'), /bindDocumentLang\(globalThis\.CloudeI18n, document\)/);
  assert.match(read('client/js/terminal.js'), /window\.TerminalScreenReader\.bind\(this\.term\)/);
  assert.match(read('client/js/preferences-transport.js'), /TerminalScreenReader\.apply\(\)/);
  assert.match(read('client/index.html'), /terminal-screen-reader\.js/);
  const pre = read('macOS/app-window-preload.js');
  assert.match(pre, /contract: 1,/);
  assert.match(pre, /capabilities: Object\.freeze\(\[[^\]]*'screenReader'\]/);
  assert.match(pre, /ipcRenderer\.invoke\('carnivore:screen-reader'\)/);
  assert.match(read('macOS/main.js'), /registerScreenReader\(\{/);
  assert.match(read('src/core/ui_preferences.py'), /terminal_screen_reader: Optional\[str\] = None/);
});

await t('the shell answers the page only for a registered window and pushes each OS change to every window', async () => {
  const require = createRequire(import.meta.url);
  const { registerScreenReader, CHANNEL } = require(path.join(root, 'macOS/screen-reader.js'));
  let handler = null; let onChange = null; const sent = [];
  const app = { accessibilitySupportEnabled: true, on: (name, fn) => { if (name === 'accessibility-support-changed') onChange = fn; } };
  const frame = { url: 'http://127.0.0.1:5001/' };
  const sender = { mainFrame: frame };
  const appWindow = { sendAll: (c, v) => sent.push([c, v]), ownsSender: (s) => s === sender, origin: () => 'http://127.0.0.1:5001' };
  registerScreenReader({ ipcMain: { handle: (c, fn) => { assert.equal(c, CHANNEL); handler = fn; } }, app, appWindow });
  assert.equal(await handler({ sender, senderFrame: frame }), true);
  app.accessibilitySupportEnabled = false;
  assert.equal(await handler({ sender, senderFrame: frame }), false);
  assert.equal(await handler({ sender: {}, senderFrame: frame }), false, 'a stranger is refused');
  assert.equal(await handler({ sender, senderFrame: { url: 'https://evil.example/' } }), false, 'another frame is refused');
  onChange({}, true); onChange({}, 'x');
  assert.deepEqual(sent, [[CHANNEL, true], [CHANNEL, false]]);
});

console.log(`all passed (${n})`);
