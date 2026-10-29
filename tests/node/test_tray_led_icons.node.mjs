import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { load, repo, env, snap, row, byId, walk } from './tray_menu_fixtures.mjs';

const hues = load('led-hues.js');
const tokens = load('oc-token-values.js');
const { renderGlyphPng } = load('led-glyph.js');
const { createLedIcons } = load('led-icons.js');
const presenter = load('presenter.js');
const { buildMenuModel } = load('model/index.js');
const { PEER_HASH } = load('model/sessions.js');
const { ledFor } = load('need-you.js');

const glyphOf = (signals) => hues.glyphFor(env.led.ledStateFor(signals).inner);

test('every LED inner state the web LED can answer has a glyph, and an unknown name draws as unknown', () => {
  for (const inner of env.led.INNER_STATES) assert.ok(hues.GLYPHS[inner], `no glyph for ${inner}`);
  assert.equal(hues.glyphFor('nonsense'), hues.GLYPHS.unknown);
});

test('shape rule: gray idle and gray unknown differ by shape, dead and disconnected differ in color', () => {
  const idle = glyphOf({ activity_status: 'idle' });
  const unknown = glyphOf({});
  assert.equal(idle.color, unknown.color, 'same gray hue');
  assert.notEqual(idle.shape, unknown.shape);
  assert.notDeepEqual(renderGlyphPng(idle, 2), renderGlyphPng(unknown, 2), 'the drawn pixels differ');
  const dead = glyphOf({ activity_status: 'dead' });
  const disconnected = glyphOf({ activity_status: 'idle', host_offline: 'laptop' });
  assert.notEqual(dead.color, disconnected.color);
  assert.equal(disconnected.color, tokens.TOKEN_HEX['--oc-coral']);
});

test('five hues: working green, stopped-waiting yellow, notice light blue, idle gray, disconnected red', () => {
  assert.equal(glyphOf({ activity_status: 'working' }).color, tokens.TOKEN_HEX['--oc-green']);
  assert.equal(glyphOf({ activity_status: 'question' }).color, tokens.TOKEN_HEX['--oc-yellow-bright']);
  assert.equal(glyphOf({ startup_gate: 'awaiting_startup_prompt' }).color, tokens.TOKEN_HEX['--oc-yellow-bright']);
  assert.equal(glyphOf({ activity_status: 'notice' }).color, tokens.TOKEN_HEX['--oc-cyan']);
  assert.equal(glyphOf({ activity_status: 'idle', unread: true }).shape, 'ringdot', 'finished unread wears the ring');
});

function firstDefinition(css, name) {
  const m = new RegExp(`${name}:\\s*(?:(#[0-9a-fA-F]{6})|var\\([^,]+,\\s*(#[0-9a-fA-F]{6})\\))`).exec(css);
  return m && (m[1] || m[2]).toLowerCase();
}

test('token parity: every value in oc-token-values.js equals its tokens.css definition', () => {
  const css = fs.readFileSync(path.join(repo, 'web/src/opscenter/tokens.css'), 'utf8');
  for (const [name, hex] of Object.entries(tokens.TOKEN_HEX)) {
    assert.equal(firstDefinition(css, name), hex, `${name} drifted from tokens.css`);
  }
});

test('token parity: the dead dot equals status-led.css --led-color-dead', () => {
  const css = fs.readFileSync(path.join(repo, 'client/css/status-led.css'), 'utf8');
  assert.equal(/--led-color-dead:\s*(#[0-9a-fA-F]{6})/.exec(css)[1].toLowerCase(), hues.DEAD_HEX);
});

test('tokensCss is one :root rule over exactly the table', () => {
  const css = tokens.tokensCss();
  assert.ok(css.startsWith(':root{') && css.endsWith('}'));
  for (const [name, hex] of Object.entries(tokens.TOKEN_HEX)) assert.ok(css.includes(`${name}:${hex};`));
});

test('the renderer makes real PNGs at 1x and 2x, transparent outside the glyph', () => {
  for (const scale of [1, 2]) {
    const png = renderGlyphPng(hues.GLYPHS.working, scale);
    assert.deepEqual([...png.subarray(0, 8)], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    assert.equal(png.readUInt32BE(16), 14 * scale);
    assert.equal(png.readUInt32BE(20), 14 * scale);
    const size = 14 * scale;
    const idat = png.subarray(png.indexOf('IDAT') + 4, png.indexOf('IEND') - 8);
    const raw = zlib.inflateSync(idat);
    const alphaAt = (x, y) => raw[y * (size * 4 + 1) + 1 + (y * 0) + x * 4 + 3];
    assert.equal(alphaAt(0, 0), 0, 'corner transparent');
    assert.equal(alphaAt(size / 2, size / 2), 255, 'center opaque');
  }
});

function fakeElectron() {
  const made = [];
  const theme = { shouldUseDarkColors: true };
  const nativeImage = { createFromBuffer: (buf, opts) => { const img = { buf, opts, reps: [], addRepresentation(r) { this.reps.push(r); } }; made.push(img); return img; } };
  return { made, theme, icons: createLedIcons({ nativeImage, nativeTheme: theme }) };
}

test('icons: a 1x image with a 2x representation, cached per state and appearance, dropped on invalidate', () => {
  const { made, theme, icons } = fakeElectron();
  const a = icons.iconFor({ inner: 'working', outer: 'active' });
  assert.equal(a.opts.scaleFactor, 1);
  assert.equal(a.reps[0].scaleFactor, 2);
  assert.equal(icons.iconFor({ inner: 'working', outer: 'active' }), a, 'cached');
  assert.equal(made.length, 1);
  assert.notEqual(icons.iconFor({ inner: 'idle', outer: 'steady' }), a);
  theme.shouldUseDarkColors = false;
  assert.notEqual(icons.iconFor({ inner: 'working', outer: 'active' }), a, 'a theme flip never serves the old appearance');
  icons.invalidate();
  assert.equal(icons.size(), 0);
  assert.equal(icons.iconFor(null), undefined);
});

test('icons: a failing image API yields no icon instead of a thrown error', () => {
  const icons = createLedIcons({ nativeImage: { createFromBuffer: () => { throw new Error('nope'); } }, nativeTheme: { shouldUseDarkColors: false } });
  const warn = console.warn; console.warn = () => {};
  try { assert.equal(icons.iconFor({ inner: 'working' }), undefined); } finally { console.warn = warn; }
});

test('model: Need You rows and Sessions rows carry the LED state; the sublabel word stays', () => {
  const rows = [row('1', { activity_status: 'question' }), row('2', { activity_status: 'working' }), row('3', { activity_status: 'idle', unread: true })];
  const items = buildMenuModel(snap({ listing: { reachable: true, live: true, rows, error: null } }), env);
  const needYou = byId(items, 'needyou').submenu[0];
  assert.equal(needYou.led.inner, 'waiting-permission');
  assert.ok(needYou.sublabel);
  const sessionRows = byId(items, 'sessions').submenu.filter((i) => i.id && i.id.startsWith('session.'));
  assert.equal(sessionRows.length, 3);
  for (const r of sessionRows) { assert.ok(r.led && r.led.inner); assert.ok(r.sublabel); }
  assert.equal(sessionRows.find((r) => r.id.includes('uuid') || r.id.includes('row:3')).led.outer, 'unread');
  assert.equal(ledFor(rows[0], null), null);
});

test('presenter: a row with a led gets the icon; no iconFor means no icon and no error', () => {
  const items = [{ type: 'submenu', id: 's', label: 'S', led: { inner: 'working' }, submenu: [{ type: 'normal', id: 'c', label: 'C', led: { inner: 'idle' } }] }];
  const seen = [];
  const withIcons = presenter.toTemplate(items, () => {}, (state) => { seen.push(state.inner); return { icon: state.inner }; });
  assert.deepEqual(withIcons[0].icon, { icon: 'working' });
  assert.deepEqual(withIcons[0].submenu[0].icon, { icon: 'idle' });
  const without = presenter.toTemplate(items, () => {}, null);
  assert.equal('icon' in without[0], false);
  const failing = presenter.toTemplate(items, () => {}, () => undefined);
  assert.equal('icon' in failing[0], false);
});

test('peer rows open the Pack computers tab, a real route, not the sessions list', () => {
  assert.equal(PEER_HASH, '#pack/computers');
  const pack = fs.readFileSync(path.join(repo, 'web/src/lib/pack-page/pack-hash.ts'), 'utf8');
  assert.ok(pack.includes("'computers'") && /packFragment/.test(pack), 'the route the row names exists in the app');
  const rows = [row('1'), row('2', { host_key: 'peer-a', host_label: 'Studio', session: undefined })].map((r, i) => (i ? { ...r, session: { id: 'remote:peer-a:x' } } : r));
  const items = buildMenuModel(snap({ listing: { reachable: true, live: true, rows, error: null } }), env);
  const peer = byId(items, 'peer.peer-a');
  assert.deepEqual(peer.action, { kind: 'app.open', hash: '#pack/computers' });
  walk(items, (i) => { if (i.id === 'sessions.all') assert.equal(i.action.hash, '#sessions'); });
});

test('an over-limit row wears the skull: ledFor passes usage_limit like the sidebar does', () => {
  const limited = row('9', { usage_limit: { resets_at: '2026-10-20T21:00:00-04:00' } });
  assert.equal(ledFor(limited, env.led).inner, 'limit');
  assert.equal(hues.glyphFor('limit').shape, 'skull');
  assert.notEqual(ledFor(row('9'), env.led).inner, 'limit');
});
