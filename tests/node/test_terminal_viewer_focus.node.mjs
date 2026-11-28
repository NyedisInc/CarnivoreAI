import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const dir = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(dir, '..', '..', 'client', 'js', 'terminal-viewer-focus.js'), 'utf8');
const ctx = { console };
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(src, ctx);
const decide = ctx.TerminalViewerFocus.decideFocus;
const decideFocus = (state) => JSON.parse(JSON.stringify(decide(state)));

const c = (key, withdrawn = false) => ({ key, withdrawn });
const base = { windowFocused: true, visible: true };

const many = Array.from({ length: 11 }, (_, i) => c(`t${i}`));
const out = decideFocus({ ...base, clients: many, lastFocusedKey: 't4' });
assert.deepEqual(Object.keys(out).filter((k) => out[k]), ['t4']);
assert.ok(Object.values(decideFocus({ ...base, clients: many, lastFocusedKey: null })).every((v) => !v));
assert.deepEqual(decideFocus({ ...base, clients: [c('a')], lastFocusedKey: null }), { a: true });
assert.deepEqual(decideFocus({ ...base, windowFocused: false, clients: [c('a')], lastFocusedKey: 'a' }), { a: false });
assert.deepEqual(decideFocus({ ...base, visible: false, clients: [c('a')], lastFocusedKey: 'a' }), { a: false });
assert.deepEqual(decideFocus({ ...base, clients: [c('a', true), c('b')], lastFocusedKey: 'a' }), { a: false, b: true });
console.log('ok');
