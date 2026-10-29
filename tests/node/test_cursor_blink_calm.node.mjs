import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const repo = path.join(import.meta.dirname, '..', '..');
const read = (rel) => fs.readFileSync(path.join(repo, rel), 'utf8');

test('pin: vendored xterm blinks only the focused terminal', () => {
  const hint = 'Re-verify against client/vendor/xterm/VERSION.md after an xterm upgrade (A3 relies on this).';
  const webgl = read('client/vendor/xterm/xterm-addon-webgl.js');
  const has = (text, re) => assert.ok(re.test(text), hint);
  has(webgl, /isFocused&&this\._restartInterval\(\)/);
  has(webgl, /handleBlur\(\)\{.{0,200}?_cursorBlinkStateManager\.value.{0,60}?\.pause\(\)/s);
  has(read('client/vendor/xterm/xterm.js'), /isFocused\)\w+&&\w+\.push\("xterm-cursor-blink"\)/);
});

function rig() {
  const attrs = new Map();
  const listeners = {};
  const mq = { matches: false, cbs: [], addEventListener(t, cb) { this.cbs.push(cb); } };
  const root = {
    getAttribute: (k) => (attrs.has(k) ? attrs.get(k) : null),
    setAttribute: (k, v) => attrs.set(k, v),
    removeAttribute: (k) => attrs.delete(k),
  };
  const observers = [];
  class MO { constructor(cb) { this.cb = cb; observers.push(this); } observe() {} disconnect() {} }
  const document = { documentElement: root, addEventListener: (t, cb) => { (listeners[t] ||= []).push(cb); } };
  const window = {};
  const ctx = vm.createContext({ window, document, matchMedia: () => mq, MutationObserver: MO, WeakRef, Set, localStorage: { getItem: () => null, setItem() {} }, globalThis: { } });
  vm.runInContext(read('client/js/motion-setting.js'), ctx);
  return {
    Motion: window.Motion, attrs, mq,
    emitCalm: () => (listeners['carnivore:calm'] || []).forEach((cb) => cb()),
    fireTypes: () => observers.forEach((o) => o.cb()),
  };
}

test('blink follows calm, type switch and OS Reduce Motion', () => {
  const r = rig();
  const a = { options: { cursorBlink: false } };
  const b = { options: { cursorBlink: false } };
  r.Motion.bindCursorBlink(a);
  r.Motion.bindCursorBlink(b);
  assert.deepEqual([a.options.cursorBlink, b.options.cursorBlink], [true, true]);

  r.attrs.set('data-calm', 'blur');
  r.emitCalm();
  assert.deepEqual([a.options.cursorBlink, b.options.cursorBlink], [false, false]);
  r.attrs.delete('data-calm');
  r.emitCalm();
  assert.deepEqual([a.options.cursorBlink, b.options.cursorBlink], [true, true]);

  r.attrs.set('data-anim-off', 'cursor-blink');
  r.fireTypes();
  assert.equal(a.options.cursorBlink, false);
  r.attrs.delete('data-anim-off');
  r.fireTypes();
  assert.equal(a.options.cursorBlink, true);

  r.mq.matches = true;
  r.mq.cbs.forEach((cb) => cb());
  assert.deepEqual([a.options.cursorBlink, b.options.cursorBlink], [false, false]);
  r.mq.matches = false;
  r.mq.cbs.forEach((cb) => cb());
  assert.equal(a.options.cursorBlink, true);
});
