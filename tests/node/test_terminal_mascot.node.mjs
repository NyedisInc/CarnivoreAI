
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal-mascot.js'), 'utf8');
const CAPTURE = fs.readFileSync(path.join(ROOT, 'tests/fixtures/clawd_startup_capture.ansi.txt'), 'utf8');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function parseCapture(raw) {
  return raw.split('\n').map((line) => {
    const cells = [];
    let fg = null;
    const re = /\x1b\[([0-9;]*)m|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|(.)/gu;
    for (const m of line.matchAll(re)) {
      if (m[1] !== undefined) {
        if (m[1] === '0' || m[1] === '39') fg = null;
        const c = m[1].match(/^38;5;(\d+)$/);
        if (c) fg = Number(c[1]);
      } else if (m[2] !== undefined) cells.push({ ch: m[2], fg });
    }
    return cells;
  });
}

function makeBuffer(lines) {
  return {
    length: lines.length, baseY: 0, cursorY: lines.length - 1,
    getLine(y) {
      const cells = lines[y];
      if (!cells) return undefined;
      return {
        translateToString: () => cells.map((c) => c.ch).join('').padEnd(110),
        getCell: (x) => cells[x] && {
          getFgColorMode: () => (cells[x].fg === null ? 0 : 1),
          getFgColor: () => cells[x].fg,
        },
      };
    },
  };
}

function makeEl() {
  const el = {
    style: {}, attrs: {}, parentNode: null, isConnected: false, className: '',
    setAttribute(k, v) { el.attrs[k] = v; },
  };
  return el;
}

function load(lines) {
  const state = { lines, viewportY: 0, cols: 110, rows: 42 };
  const fire = { parsed: null, scroll: null };
  const children = [];
  const screen = {
    appendChild: (e) => { e.parentNode = screen; e.isConnected = true; children.push(e); },
    removeChild: (e) => { e.parentNode = null; e.isConnected = false; children.splice(children.indexOf(e), 1); },
  };
  const bufferObj = {
    get length() { return state.lines.length; }, baseY: 0, cursorY: 0,
    get viewportY() { return state.viewportY; },
    getLine: (y) => makeBuffer(state.lines).getLine(y),
    onBufferChange: () => ({ dispose() {} }),
  };
  const term = {
    buffer: { active: bufferObj, onBufferChange: () => ({ dispose() {} }) },
    get cols() { return state.cols; }, get rows() { return state.rows; },
    element: { querySelector: (sel) => (sel === '.xterm-screen' ? screen : null) },
    onWriteParsed: (fn) => { fire.parsed = fn; return { dispose() {} }; },
    onScroll: (fn) => { fire.scroll = fn; return { dispose() {} }; },
    onResize: () => ({ dispose() {} }),
  };
  const sandbox = {
    console: { log() {}, warn() {} }, setTimeout, clearTimeout, Date,
    document: { createElement: makeEl },
  };
  sandbox.window = sandbox;
  vm.runInNewContext(SRC, sandbox);
  return { M: sandbox.TerminalMascot, term, state, children, fire };
}

const lines = parseCapture(CAPTURE);
const manifest = { id: 'lovecraft', source: 'builtin', mascot: 'mascot.svg' };

test('matches the real Clawd block and reports its row and column', () => {
  const { M, term } = load(lines);
  assert.deepEqual({ ...M.findClawd(term.buffer.active) }, { line: 2, col: 0 });
});

test('rejects near misses: a changed glyph, a mixed colour, a missing row', () => {
  const clone = () => lines.map((l) => l.map((c) => ({ ...c })));
  const changed = clone(); changed[2][3].ch = '▜';
  const recoloured = clone(); recoloured[3][0].fg = 200;
  const truncated = clone().slice(0, 4);
  for (const bad of [changed, recoloured, truncated]) {
    const { M, term } = load(bad);
    assert.equal(M.findClawd(term.buffer.active), null);
  }
});

test('sync lays a 9 x 3 sprite over the found cells, and only for a theme with a mascot', async () => {
  const { M, term, children } = load(lines);
  const client = { term };
  M.sync(client, { id: 'dracula', source: 'builtin' });
  await sleep(300);
  assert.equal(children.length, 0);
  M.sync(client, manifest);
  await sleep(300);
  assert.equal(children.length, 1);
  const st = children[0].style;
  assert.deepEqual([st.left, st.width], ['0%', `${9 / 110 * 100}%`]);
  assert.equal(st.top, `${2 / 42 * 100}%`);
  assert.equal(st.height, `${3 / 42 * 100}%`);
  assert.match(st.backgroundImage, /lovecraft\/mascot\.svg/);
  assert.equal(M.mascotUrlFor(manifest), '/static/css/themes/lovecraft/mascot.svg');
  assert.equal(M.mascotUrlFor({ id: 'x', source: 'user', mascot: '../a.svg' }), null);
  M.sync(client, { id: 'dracula', source: 'builtin' });
  assert.equal(children.length, 0);
});

test('a banner redrawn after startup (as /clear does) is found again, and a placed sprite is not re-added', async () => {
  const { M, term, state, children, fire } = load(lines);
  M.sync({ term }, manifest);
  await sleep(300);
  assert.equal(children.length, 1);
  fire.parsed(); await sleep(300);
  assert.equal(children.length, 1, 'a verified sprite is left alone');
  const blank = lines.map((l) => l.map((c) => ({ ch: ' ', fg: null })));
  state.lines = blank;
  fire.parsed(); await sleep(300);
  assert.equal(children.length, 0);
  const moved = blank.map((l) => l.map((c) => ({ ...c })));
  for (let r = 0; r < 3; r++) moved[3 + r] = [{ ch: ' ', fg: null }, ...lines[2 + r]];
  state.lines = moved;
  fire.parsed(); await sleep(300);
  assert.equal(children.length, 1);
  assert.equal(children[0].style.top, `${3 / 42 * 100}%`);
  assert.equal(children[0].style.left, `${1 / 110 * 100}%`);
});

test('the sprite leaves with its rows on a scroll and is found again when they return', async () => {
  const { M, term, state, children, fire } = load(lines);
  M.sync({ term }, manifest);
  await sleep(300);
  assert.equal(children.length, 1);
  state.viewportY = 5; fire.scroll();
  assert.equal(children.length, 0);
  state.viewportY = 0; fire.scroll();
  assert.equal(children.length, 1);
  assert.equal(children[0].style.display, undefined);
});
