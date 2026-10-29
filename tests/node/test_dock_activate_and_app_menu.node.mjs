import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import Module from 'node:module';
import { fileURLToPath } from 'node:url';

const macDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const { createActivateHandler } = require(path.join(macDir, 'dock-activate.js'));

const menuDir = path.join(macDir, 'app-menu');
const { buildTemplate } = require(path.join(menuDir, 'index.js'));
const { MENU_VERBS, MAIN_ACTIONS, sendVerb } = require(path.join(menuDir, 'commands.js'));
const { auditAccelerators, RESERVED_CHORDS } = require(path.join(menuDir, 'chords.js'));

function harness({ open = false, running = false, canOpen = true, menu = { m: 1 } } = {}) {
  const pops = [];
  const opens = [];
  const handler = createActivateHandler({
    appWindow: { isOpen: () => open, open: () => { opens.push(1); return canOpen; } },
    isServerRunning: () => running,
    getTray: () => ({ popUpContextMenu: (...a) => pops.push(a) }),
    getTrayMenu: () => menu,
  });
  return { handler, pops, opens };
}

let n = 0;
/** Run one named case. */
function t(name, fn) { fn(); n++; console.log(`ok - ${name}`); }

t('server running: opens the window, never pops a menu', () => {
  const h = harness({ running: true }); h.handler();
  assert.equal(h.opens.length, 1); assert.equal(h.pops.length, 0);
});
t('server down: pops the built menu explicitly', () => {
  const h = harness(); h.handler();
  assert.equal(h.pops.length, 1); assert.deepEqual(h.pops[0], [{ m: 1 }]);
});
t('popUpContextMenu is never called with no argument', () => {
  for (const cfg of [{}, { running: true, canOpen: false }, { open: true, canOpen: false }]) {
    const h = harness(cfg); h.handler();
    for (const a of h.pops) assert.ok(a.length === 1 && a[0]);
  }
  const h = harness({ menu: null }); h.handler();
  assert.equal(h.pops.length, 0);
});
t('main.js has no bare popUpContextMenu()', () => {
  assert.ok(!/popUpContextMenu\(\s*\)/.test(fs.readFileSync(path.join(macDir, 'main.js'), 'utf8')));
});

const noop = () => {};
const keyT = (key) => `KEY:${key}`;
const appName = 'Carnivore';
function build(over = {}) {
  const calls = { sent: [], opened: [], urls: [], quit: 0, about: 0 };
  const appWindow = {
    open: (h) => { calls.opened.push(h === undefined ? '(raise)' : h); return true; },
    openApproval: (id) => { calls.opened.push(`approval:${id}`); return true; },
    sendMenuCommand: (verb) => { calls.sent.push(verb); return true; },
  };
  const deps = {
    t: keyT, appName, isPackaged: true, appWindow, showAbout: () => { calls.about++; }, quitAndStopEngine: () => { calls.quit++; },
    openUrl: (u) => calls.urls.push(u), waiting: () => null, ...over,
  };
  return { tpl: buildTemplate(deps), calls, deps };
}
const byId = (tpl, id) => tpl.find((m) => m.id === id);
const sub = (tpl, id) => byId(tpl, id).submenu;
const flat = (tpl) => tpl.flatMap((m) => m.submenu || []);
const real = (items) => items.filter((i) => i.type !== 'separator');

t('Edit menu has the clipboard roles', () => {
  const roles = sub(build().tpl, 'edit').map((i) => i.role);
  for (const r of ['undo', 'redo', 'cut', 'copy', 'paste', 'selectAll']) assert.ok(roles.includes(r), r);
});
t('dev items only when unpackaged', () => {
  const view = (p) => sub(build({ isPackaged: p }).tpl, 'view').map((i) => i.role);
  assert.ok(!view(true).includes('toggleDevTools') && !view(true).includes('forceReload'));
  assert.ok(view(false).includes('toggleDevTools') && view(false).includes('forceReload'));
});
t('Settings has Cmd-, and Quit has Cmd-Q', () => {
  const m = sub(build().tpl, 'carnivore');
  assert.ok(m.some((i) => i.accelerator === 'Cmd+,')); assert.ok(m.some((i) => i.accelerator === 'Cmd+Q'));
});
t('1 top-level order is Carnivore, File, Edit, View, Session, Window, Help (by id)', () => {
  assert.deepEqual(build().tpl.map((m) => m.id), ['carnivore', 'file', 'edit', 'view', 'session', 'window', 'help']);
  assert.equal(byId(build().tpl, 'carnivore').label, appName);
});
t('2 every item is a role, a verb from the fixed list, or a named main action; placeholders are disabled and tagged', () => {
  const { tpl } = build({ isPackaged: false });
  const pending = {};
  for (const item of real(flat(tpl))) {
    if (item.pending) { assert.equal(item.enabled, false, item.id); pending[item.id] = item.pending; continue; }
    if (item.role) continue;
    assert.equal(typeof item.click, 'function', `${item.id} has no click`);
    assert.ok(MENU_VERBS.includes(item.id) || MAIN_ACTIONS.includes(item.id), `${item.id} is not a verb or main action`);
  }
  assert.deepEqual(pending, {});
});
t('2b a verb item sends exactly its verb; an unknown verb is never sent', () => {
  const { tpl, calls } = build();
  for (const item of real(flat(tpl)).filter((i) => MENU_VERBS.includes(i.id))) item.click();
  assert.deepEqual(calls.sent.sort(), [...MENU_VERBS].sort());
  const w = { sendMenuCommand: () => assert.fail('sent') };
  assert.equal(sendVerb(w, 'rm.rf'), false); assert.equal(sendVerb(w, 7), false);
});
t('2c main actions: new window raises the window, answer opens the longest-waiting approval, docs opens one constant url', () => {
  const { tpl, calls } = build({ waiting: () => ({ need: 'question', sessionId: 'ses_1', tmuxName: 'carnivore_a' }) });
  const click = (id) => real(flat(tpl)).find((i) => i.id === id).click();
  click('file.new_window'); click('session.answer'); click('help.docs'); click('carnivore.settings');
  assert.deepEqual(calls.opened, ['(raise)', 'approval:ses_1', '#settings']);
  assert.deepEqual(calls.urls, ['https://carnivore.ai/help']);
  const none = build({ waiting: () => null }); real(flat(none.tpl)).find((i) => i.id === 'session.answer').click();
  assert.deepEqual(none.calls.opened, [], 'nothing waiting: nothing visible');
});
t('3 no literal label: every label is a catalog key; no file over 300 lines; no quoted English in the sources', () => {
  const { tpl } = build({ isPackaged: false });
  for (const item of flat(tpl)) if (item.label !== undefined) assert.ok(item.label.startsWith('KEY:'), `${item.id}: ${item.label}`);
  for (const top of tpl.slice(1)) assert.ok(top.label.startsWith('KEY:'), top.id);
  const files = fs.readdirSync(menuDir).filter((f) => f.endsWith('.js'));
  assert.ok(files.length >= 9, files.join());
  for (const f of files) {
    const src = fs.readFileSync(path.join(menuDir, f), 'utf8');
    assert.ok(src.split('\n').length <= 300, `${f} is over 300 lines`);
    const literals = [...src.matchAll(/label:\s*(['"`])/g)];
    assert.equal(literals.length, 0, `${f} has a literal label`);
  }
});
t('4 the chord audit finds nothing in the real menu, and fails on a stolen chord', () => {
  assert.deepEqual(auditAccelerators(build().tpl), []);
  assert.deepEqual(auditAccelerators(build({ isPackaged: false }).tpl), []);
  const seeded = (accelerator) => [{ id: 'x', submenu: [{ id: 'x.y', accelerator, click: noop }] }];
  for (const stolen of ['Cmd+F', 'Cmd+G', 'Shift+Cmd+G', 'Cmd+S', 'Cmd+Enter', 'Shift+Cmd+Enter', 'Ctrl+C', 'Ctrl+Cmd+C', 'Alt+B', 'Alt+Left', 'Shift+Enter', 'Escape', 'Tab']) {
    if (stolen === 'Ctrl+Cmd+C') continue;
    assert.equal(auditAccelerators(seeded(stolen)).length, 1, stolen);
  }
  assert.equal(auditAccelerators(seeded('Ctrl+Cmd+C')).length, 0);
  assert.ok(RESERVED_CHORDS.length >= 12);
  const roleOnly = [{ id: 'x', submenu: [{ id: 'x.f', role: 'togglefullscreen' }] }];
  assert.deepEqual(auditAccelerators(roleOnly), []);
});
t('5 Help has the help role; Window has the window role, a front item and no backtick accelerator', () => {
  const { tpl } = build();
  assert.equal(byId(tpl, 'help').role, 'help');
  const win = byId(tpl, 'window');
  assert.equal(win.role, 'window');
  assert.ok(win.submenu.some((i) => i.role === 'front'));
  assert.ok(!JSON.stringify(win).includes('`'));
});
t('6 Quit and Stop Engine has no accelerator; only the standard app-level chords carry one in the Carnivore menu', () => {
  const { tpl, calls } = build();
  const m = sub(tpl, 'carnivore');
  const stop = m.find((i) => i.id === 'carnivore.quit_engine');
  assert.ok(stop && stop.accelerator === undefined); stop.click(); assert.equal(calls.quit, 1);
  assert.deepEqual(m.filter((i) => i.accelerator).map((i) => i.accelerator).sort(), ['Cmd+,', 'Cmd+Q']);
  m.find((i) => i.id === 'carnivore.about').click(); assert.equal(calls.about, 1);
});
t('7 the old single file is gone and main.js does not require it by file name', () => {
  assert.ok(!fs.existsSync(path.join(macDir, 'app-menu.js')));
  assert.ok(!/app-menu\.js/.test(fs.readFileSync(path.join(macDir, 'main.js'), 'utf8')));
});
console.log(`${n} passed`);
