import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(root, 'client/js/terminal-option-meta.js'), 'utf8');

function world(shared) {
  const store = new Map();
  const subs = [];
  const bridge = {
    value: shared,
    read(field, local) { return this.value === undefined ? local() : this.value; },
    follow(field, fn) { subs.push([field, fn]); return () => {}; },
  };
  const sandbox = {
    console, WeakRef, Set, Map,
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, v) },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.PreferenceBridge = bridge;
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox);
  const push = (value) => subs.filter(([f]) => f === 'mac_option_is_meta').forEach(([, fn]) => fn(value));
  return { mod: sandbox.TerminalOptionMeta, bridge, push, store, subs };
}
const term = () => ({ options: { macOptionIsMeta: false } });

let n = 0;
/** Run one named case. */
function t(name, fn) { fn(); n++; console.log(`ok - ${name}`); }

t('a terminal bound while the preference is off stays off; bound while on starts on', () => {
  const off = world(false); const a = term(); off.mod.bind(a); assert.equal(a.options.macOptionIsMeta, false);
  const on = world(true); const b = term(); on.mod.bind(b); assert.equal(b.options.macOptionIsMeta, true);
});
t('setting the preference true flips every live terminal on, false flips them back, with no rebind', () => {
  const w = world(false); const a = term(); const b = term(); w.mod.bind(a); w.mod.bind(b);
  w.push(true); assert.equal(a.options.macOptionIsMeta, true); assert.equal(b.options.macOptionIsMeta, true);
  w.push(false); assert.equal(a.options.macOptionIsMeta, false); assert.equal(b.options.macOptionIsMeta, false);
  w.push(null); assert.equal(a.options.macOptionIsMeta, false, 'a field returned to its default is off');
});
t('follows the bridge once however many terminals bind', () => {
  const w = world(false); for (let i = 0; i < 4; i++) w.mod.bind(term());
  assert.equal(w.subs.length, 1);
});
t('apply() re-reads the bridge (a reconnect refresh) and repaints', () => {
  const w = world(false); const a = term(); w.mod.bind(a);
  w.bridge.value = true; assert.equal(w.mod.apply(), true); assert.equal(a.options.macOptionIsMeta, true);
});
t('before hydration the last value this browser saw is used; absent means off', () => {
  const w = world(true); w.mod.bind(term());
  const cold = world(undefined); const c = term(); cold.mod.bind(c); assert.equal(c.options.macOptionIsMeta, false, 'absent is off');
  w.bridge.value = undefined; const d = term(); w.mod.bind(d); assert.equal(d.options.macOptionIsMeta, true, 'local copy');
});
t('terminal.js binds each new xterm, and the frozen XTERM_OPTIONS does not carry the value', () => {
  assert.match(fs.readFileSync(path.join(root, 'client/js/terminal.js'), 'utf8'), /window\.TerminalOptionMeta\.bind\(this\.term\)/);
  assert.ok(!/macOptionIsMeta/.test(fs.readFileSync(path.join(root, 'client/js/terminal-client-factory.js'), 'utf8')));
  assert.match(fs.readFileSync(path.join(root, 'client/index.html'), 'utf8'), /terminal-option-meta\.js/);
});
console.log(`${n} passed`);
