import fs from 'node:fs';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const src = fs.readFileSync(new URL('../../client/js/folder-picker-modal.js', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../../client/css/new-agent-flow.css', import.meta.url), 'utf8');

const row = src.match(/<div class="folder-picker-item[^"]*"[\s\S]*?<\/div>/)[0];
assert.match(row, /folder-picker-item config-editor-toggle/);
assert.match(row, /folder-picker-name config-editor-node-name/);
assert.doesNotMatch(row, /<br|<div[^>]*>[\s\S]*<div/);
assert.match(css, /\.folder-picker-list\s*\{[^}]*overflow-x:\s*hidden/);
assert.match(css, /folder-picker-item\.config-editor-toggle\s*\{[^}]*padding:\s*0 6px 0 4px/);

const els = [];
const mk = (cls) => ({ classList: { _s: new Set(), toggle(c, on) { on ? this._s.add(c) : this._s.delete(c); }, has(c) { return this._s.has(c); } },
  scrollIntoView() {}, dataset: {}, addEventListener() {}, className: cls });
let keyHandler; let browsed = [];
const listEl = { innerHTML: '', focus() { ctx.document.activeElement = listEl; }, querySelectorAll(sel) { return sel === '.folder-picker-item' ? els : []; } };
const overlay = { className: '', innerHTML: '', addEventListener() {}, 
  querySelector(sel) { return { '#folder-picker-list': listEl }[sel] || { addEventListener() {}, set value(v) {}, focus() {}, textContent: '', className: '' }; } };
const ctx = { console, setTimeout, clearTimeout,
  document: { createElement: () => overlay, body: { appendChild() {}, removeChild() {} }, activeElement: null,
    addEventListener(t, h) { if (t === 'keydown') keyHandler = h; }, removeEventListener() {} },
  API: { async browseDirectory(p) { browsed.push(p); return { path: '/r', parent: '/', entries: [{ name: 'alpha', path: '/r/alpha' }, { name: 'beta', path: '/r/beta' }] }; } },
  SessionStatusUI: {} };
ctx.window = ctx; vm.createContext(ctx); vm.runInContext(src, ctx);
const done = ctx.FolderPickerModal.open();
await new Promise((r) => setTimeout(r, 20));
els.push(mk(), mk());
const key = (k) => keyHandler({ key: k, preventDefault() {} });
key('ArrowDown'); assert.ok(els[0].classList.has('folder-picker-item-active'));
key('ArrowDown'); assert.ok(els[1].classList.has('folder-picker-item-active'));
key('ArrowUp'); assert.ok(els[0].classList.has('folder-picker-item-active'));
key('b'); assert.ok(els[1].classList.has('folder-picker-item-active'));
key('Enter'); await new Promise((r) => setTimeout(r, 10));
assert.equal(browsed.at(-1), '/r/beta');

const upBtn = { tagName: 'BUTTON' };
await keyOn(upBtn, 'Enter', false);
const before = browsed.length;
async function keyOn(el, k, expectHandled) {
  ctx.document.activeElement = el; let prevented = false;
  keyHandler({ key: k, preventDefault() { prevented = true; } });
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(prevented, expectHandled, `${k} handled=${expectHandled}`);
}
await keyOn(upBtn, ' ', false);
assert.equal(browsed.length, before);
await keyOn(upBtn, 'a', true);
assert.equal(ctx.document.activeElement, listEl);
assert.ok(els[0].classList.has('folder-picker-item-active'));
await keyOn(upBtn, 'Enter', true);
assert.equal(browsed.at(-1), '/r/alpha');

key('Escape'); assert.equal(await done, null);
console.log('ok');
