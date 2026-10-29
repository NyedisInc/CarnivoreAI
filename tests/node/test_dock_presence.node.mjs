import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { macDir, load, env, snap, row, led, t, walk, byId } from './tray_menu_fixtures.mjs';

const require = createRequire(import.meta.url);
const { createDockPresence } = require(path.join(macDir, 'dock-presence.js'));
const { buildMenuModel } = load('model/index.js');
const sessionLink = (a) => `session/${encodeURIComponent(a.tmuxName || a.sessionId)}`;

function make(over = {}) {
  const calls = { badge: [], menu: [], bounce: [], app: [], approval: [] };
  const app = over.app === undefined ? { dock: { setBadge: (v) => calls.badge.push(v), setMenu: (m) => calls.menu.push(m), bounce: (k) => calls.bounce.push(k) } } : over.app;
  const presence = createDockPresence({ app, Menu: { buildFromTemplate: (tpl) => ({ tpl }) }, platform: over.platform || 'darwin',
    openApp: (h) => calls.app.push(h), openApproval: (id) => { calls.approval.push(id); return true; }, sessionLink,
    isWindowFocused: () => !!over.focused });
  return { calls, presence, push: (rows, extra = {}) => presence.update({ rows, reachable: true, ...extra }, { led, t }) };
}
const q = (id, extra = {}) => row(id, { activity_status: 'question', ...extra });
const gate = (id) => row(id, { startup_gate: 'awaiting_startup_prompt' });

test('badge equals the tray need-you count on one fixture', () => {
  const fixture = [q('1'), gate('2'), row('3', { activity_status: 'working' }), row('4'),
    q('5', { host_key: 'peer-x', host_label: 'other' })];
  const model = buildMenuModel(snap({ listing: { rows: fixture, reachable: true } }), env);
  const trayCount = byId(model, 'needyou').badge.count;
  assert.ok(trayCount >= 2, 'fixture must wait on at least a question and a gate');
  const { calls, push } = make();
  push(fixture);
  assert.deepEqual(calls.badge, [String(trayCount)]);
  push([row('4')]);
  assert.equal(calls.badge.at(-1), '');
});

test('an unmeasured listing is never zero', () => {
  const { calls, push, presence } = make();
  push([q('1'), q('2'), q('3')]);
  const before = [calls.badge.length, calls.menu.length];
  push(null, { reachable: false });
  presence.update({ rows: [], reachable: false }, { led, t });
  presence.update({ rows: null, reachable: true }, { led, t });
  assert.deepEqual([calls.badge.length, calls.menu.length], before);
});

test('no churn: same listing sets once, a changed label rebuilds the menu', () => {
  const { calls, push } = make();
  push([q('1')]); push([q('1')]);
  assert.equal(calls.badge.length, 1);
  assert.equal(calls.menu.length, 1);
  push([q('1', { label: 'renamed' })]);
  assert.equal(calls.menu.length, 2);
  assert.equal(calls.badge.length, 1);
});

test('menu items route and cap', () => {
  const { calls, push } = make();
  const many = Array.from({ length: 10 }, (_, i) => q(String(i + 10), { project_name: `p${i}`, at: `2026-10-17T10:0${i}:00Z` }));
  push([...many, gate('2'), row('7', { host_key: 'peer-x', project_name: 'remote-only', at: '2026-12-01T00:00:00Z' })]);
  assert.equal(calls.badge.at(-1), '11');
  const tpl = calls.menu.at(-1).tpl;
  const find = (id) => tpl.find((i) => i.id === id);
  find('new').click();
  assert.deepEqual(calls.app, ['']);
  const recent = find('recent').submenu;
  assert.equal(recent.length, 5);
  assert.deepEqual(recent.map((i) => i.label), ['p9', 'p8', 'p7', 'p6', 'p5']);
  recent[0].click();
  assert.equal(calls.app.at(-1), 'session/p9');
  const waiting = tpl.filter((i) => i.id && i.id.startsWith('wait:'));
  assert.equal(waiting.length, 8);
  assert.equal(find('needyou').label, '11 Need You');
  waiting[0].click();
  assert.equal(calls.approval.length, 1);
  const g = tpl.filter((i) => i.id && i.id.endsWith(':gate'));
  assert.equal(g.length, 0, 'gate sorts after the cap in listing order');
  const r = make(); r.push([gate('2')]);
  r.calls.menu.at(-1).tpl.find((i) => i.id && i.id.startsWith('wait:')).click();
  assert.deepEqual(r.calls.app, ['session/carnivore_2']);
  assert.equal(r.calls.approval.length, 0);
  const e = make(); e.push([q('1')]);
  assert.equal(e.calls.menu.at(-1).tpl.find((i) => i.id === 'recent'), undefined);
});

test('bounce rules', () => {
  const { calls, push } = make();
  push([q('1')]);
  assert.equal(calls.bounce.length, 0, 'first measured listing seeds');
  push([q('1'), q('2')]);
  assert.deepEqual(calls.bounce, ['informational']);
  push([q('1'), q('2')]);
  assert.equal(calls.bounce.length, 1, 'persisting question does not repeat');
  push([q('1'), q('2'), q('3'), q('4')]);
  assert.equal(calls.bounce.length, 2, 'two new in one update hop once');
  push([q('1'), q('2'), q('3'), q('4'), gate('5')]);
  assert.equal(calls.bounce.length, 2, 'a gate never bounces');
  push([q('2'), q('3'), q('4')]);
  push([q('1'), q('2'), q('3'), q('4')]);
  assert.equal(calls.bounce.length, 3, 'asked again bounces again');
  push(null, { reachable: false });
  push([q('1'), q('2'), q('3'), q('4'), q('9')]);
  assert.equal(calls.bounce.length, 3, 'reconnect seeds');
  const f = make({ focused: true });
  f.push([row('1')]); f.push([q('1')]);
  assert.equal(f.calls.bounce.length, 0, 'focused window suppresses');
});

test('no Dock means no-op', () => {
  for (const o of [{ app: {} }, { app: null }, { platform: 'linux' }]) {
    const { calls, presence } = make(o);
    presence.update({ rows: [q('1')], reachable: true }, { led, t });
    presence.clear();
    assert.equal(calls.badge.length + calls.menu.length + calls.bounce.length, 0);
  }
});

test('source: app.dock lives only in the guarded dock-presence module', () => {
  const src = fs.readFileSync(path.join(macDir, 'dock-presence.js'), 'utf8');
  assert.ok(!/require\('electron'\)/.test(src));
  const uses = src.split('\n').filter((l) => /app\.dock/.test(l) && !l.trim().startsWith('//'));
  assert.equal(uses.length, 1);
  assert.match(uses[0], /platform === 'darwin'/);
  assert.ok(!/(^|\W)'(New|Recent)[^']*'/.test(src.replace(/\/\/.*$/gm, '')), 'labels come from the catalog');
  for (const f of fs.readdirSync(macDir).filter((n) => n.endsWith('.js') && n !== 'dock-presence.js')) {
    assert.ok(!/app\.dock\./.test(fs.readFileSync(path.join(macDir, f), 'utf8')), `${f} calls app.dock`);
  }
  assert.ok(/waitingRows/.test(fs.readFileSync(path.join(macDir, 'tray-menu/model/header.js'), 'utf8')));
});
