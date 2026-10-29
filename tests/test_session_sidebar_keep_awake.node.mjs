import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(__dirname, '..', 'client', 'js', 'session-sidebar-keep-awake.js'), 'utf8');

function load(store) {
  const listeners = {};
  const window = {
    CloudeWeb: store === undefined ? undefined : { autoSleep: store },
    addEventListener: (type, fn) => { listeners[type] = fn; },
  };
  const ctx = {
    window,
    console: { log() {}, error() {} },
    globalThis: null,
  };
  ctx.globalThis = {
    CloudeI18n: { t: (key, params) => `${key}|${params && params.name}` },
    CloudeGlyphs: { glyphSvg: (name) => `<svg data-glyph="${name}"></svg>` },
  };
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  return { api: window.SessionSidebarKeepAwake, window, listeners };
}

let passed = 0;
let failed = 0;
async function test(name, fn) {
  try { await fn(); passed += 1; } catch (err) { failed += 1; console.error(`FAIL ${name}\n`, err); }
}

await test('a click flips the flag and forces a repaint', async () => {
  const writes = [];
  const { api } = load({
    isKeptAwake: () => false,
    setKeepAwake: async (name, on) => { writes.push([name, on]); },
  });
  let painted = 0;
  const ctrl = { repaint: () => { painted += 1; } };
  const el = { getAttribute: () => 'carnivore_api' };
  await api.onClick(ctrl, el);
  assert.deepEqual(writes, [['carnivore_api', true]]);
  assert.equal(painted, 1);
});

await test('the change event repaints the drawer', () => {
  const { listeners, window } = load({ isKeptAwake: () => false });
  let painted = 0;
  window.SessionSidebar = { repaint: () => { painted += 1; } };
  listeners['cloude:auto-sleep-changed']();
  assert.equal(painted, 1);
});

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
