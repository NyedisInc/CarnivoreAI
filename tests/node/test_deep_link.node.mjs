import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const mac = path.join(repo, 'macOS');
const { parseDeepLink, findLinkInArgv, createFocusGate, LINK_MAX, SETTINGS_SECTIONS } = require(path.join(mac, 'deep-link.js'));
const { createLinkRouter } = require(path.join(mac, 'link-router.js'));
const { createHotkey, isSafeAccelerator } = require(path.join(mac, 'hotkey.js'));
const { handleSecondInstance } = require(path.join(mac, 'second-instance.js'));


const ACCEPTED = [
  ['carnivore://open', { kind: 'open', hash: '' }],
  ['carnivore://open/', { kind: 'open', hash: '' }],
  ['CARNIVORE://OPEN', { kind: 'open', hash: '' }],
  ['carnivore://session/my-api', { kind: 'session', hash: 'session/my-api' }],
  ['carnivore://session/my-api/', { kind: 'session', hash: 'session/my-api' }],
  ['carnivore://project/My%20Project', { kind: 'project', hash: 'session/My%20Project' }],
  ['carnivore://session/ses_abc123', { kind: 'session', hash: 'session/ses_abc123' }],
  ['carnivore://session/adopted:foo', { kind: 'session', hash: 'session/adopted%3Afoo' }],
  ['carnivore://project/caf%C3%A9', { kind: 'project', hash: 'session/caf%C3%A9' }],
  ['carnivore://approvals/ses_abc123', { kind: 'approvals', approvalId: 'ses_abc123' }],
  ['carnivore://approvals/adopted:foo', { kind: 'approvals', approvalId: 'adopted:foo' }],
  ['carnivore://settings', { kind: 'settings', hash: '#settings' }],
  ['carnivore://settings/desktop', { kind: 'settings', hash: '#settings/desktop' }],
  ['carnivore://settings/sessions/agents', { kind: 'settings', hash: '#settings/sessions/agents' }],
  ['carnivore://settings/launch_profiles', { kind: 'settings', hash: '#settings/launch_profiles' }],
];

test('accepted links map to the exact router target', () => {
  for (const [link, want] of ACCEPTED) {
    const got = parseDeepLink(link);
    assert.equal(got.ok, true, `${link} should parse: ${got.reason}`);
    assert.equal(got.kind, want.kind, link);
    for (const key of ['hash', 'approvalId']) assert.equal(got[key], want[key], `${link} ${key}`);
  }
  assert.equal(ACCEPTED.length, 15, 'the table is the whole accepted list');
});

test('the length cap is 2048: 2049 is refused as too long, 2048 reaches the later checks', () => {
  const prefix = 'carnivore://approvals/';
  const at = (n) => prefix + 'a'.repeat(n - prefix.length);
  assert.equal(LINK_MAX, 2048);
  const over = parseDeepLink(at(2049));
  assert.equal(over.ok, false);
  assert.match(over.reason, /too long/);
  const edge = parseDeepLink(at(2048));
  assert.equal(edge.ok, false);
  assert.doesNotMatch(edge.reason, /too long/);
});


const REFUSED = [
  ['http://open', 'scheme'], ['javascript:alert(1)', 'scheme'], ['file:///etc/passwd', 'scheme'], ['carnivore-x://open', 'scheme'],
  ['carnivore:open', 'scheme'], ['carnivore:/open', 'scheme'], ['carnivore:\\\\open', 'scheme'], ['open', 'scheme'], ['', 'empty'],
  ['carnivore://', 'verb'], ['carnivore:///open', 'verb'], ['carnivore://bogus', 'verb'], ['carnivore://sessions/x', 'verb'],
  ['carnivore://%6fpen', 'verb'], ['carnivore://open.evil.com', 'verb'], ['carnivore://start/ses_1', 'verb'],
  ['carnivore://answer/ses_1', 'verb'], ['carnivore://send/ses_1', 'verb'], ['carnivore://kill/ses_1', 'verb'],
  ['carnivore://open/x', 'path'], ['carnivore://open?x=1', 'query'], ['carnivore://open#x', 'fragment'],
  ['carnivore://session/', 'name'], ['carnivore://session', 'name'], ['carnivore://session//', 'name'], ['carnivore://session/..', 'name'],
  ['carnivore://session/.', 'name'], ['carnivore://project/%2e%2e', 'name'], ['carnivore://session/a%2Fb', 'name'], ['carnivore://session/a%5Cb', 'name'],
  ['carnivore://session/%00', 'name'], ['carnivore://session/a%0Ab', 'name'], ['carnivore://session/%E0%A4%A', 'escape'],
  ['carnivore://session/%252e%252e', 'twice'], ['carnivore://session/a%2541', 'twice'],
  ['carnivore://session/a/b', 'path'], ['carnivore://project/a/b', 'path'], ['carnivore://session/a?x=1', 'query'],
  ['carnivore://session/a?', 'query'], ['carnivore://session/a#x', 'fragment'], ['carnivore://session/a#', 'fragment'],
  [`carnivore://session/${'a'.repeat(201)}`, 'name'],
  ['carnivore://approvals', 'id'], ['carnivore://approvals/', 'id'], ['carnivore://approvals/a%20b', 'id'], ['carnivore://approvals/a%3Bb', 'id'],
  ['carnivore://approvals/a;b', 'id'], ['carnivore://approvals/a%2Fb', 'id'], ['carnivore://approvals/ses_1/yes', 'path'],
  ['carnivore://approvals/ses_1?answer=1', 'query'], ['carnivore://approvals/ses_1?', 'query'], [`carnivore://approvals/${'a'.repeat(201)}`, 'id'],
  ['carnivore://approvals/..', 'id'],
  ['carnivore://settings/Desktop', 'section'], ['carnivore://settings/nope', 'section'], ['carnivore://settings/desktop/Tab', 'tab'],
  ['carnivore://settings/desktop/a/b', 'path'], ['carnivore://settings/..', 'section'], ['carnivore://settings/desktop?highlight=x', 'query'],
  ['carnivore://settings/desktop#x', 'fragment'], ['carnivore://settings/plugin/x', 'section'], ['carnivore://settings//', 'section'],
  ['carnivore://settings/%64esktop', 'section'],
  ['carnivore://u:p@open', 'userinfo'], ['carnivore://u@open', 'userinfo'], ['carnivore://open:80', 'port'], ['carnivore://session:1/x', 'port'],
  ['carnivore://open\n', 'character'], ['carnivore://op\ten', 'character'], ['carnivore://session/a b', 'character'], [' carnivore://open', 'character'],
  ['carnivore://open ', 'character'], ['carnivore://session/caf\u00e9', 'character'], ['carnivore://session/a\u0000b', 'character'],
  ['carnivore://session/a\u202eb', 'character'], ['carnivore://session/a\\b', 'name'],
];

test('every malformed or unknown link is refused with a reason', () => {
  for (const [link, why] of REFUSED) {
    const got = parseDeepLink(link);
    assert.equal(got.ok, false, `${JSON.stringify(link)} must be refused`);
    assert.equal(typeof got.reason, 'string', link);
    assert.ok(got.reason.length > 0, link);
    assert.match(got.reason, new RegExp(why), `${JSON.stringify(link)} reason ${got.reason}`);
    for (const key of ['hash', 'approvalId', 'kind']) assert.equal(got[key], undefined, `a refusal carries no ${key}`);
  }
  assert.equal(REFUSED.length, 76, 'the table is the whole refused list');
});

test('a link that is not a string is refused', () => {
  for (const bad of [null, undefined, 0, 12, {}, [], ['carnivore://open'], true, { toString: () => 'carnivore://open' }, Symbol('x')]) {
    const got = parseDeepLink(bad);
    assert.equal(got.ok, false);
    assert.match(got.reason, /not a string/);
  }
});

test('settings sections match the shipped settings registry', () => {
  const src = fs.readFileSync(path.join(repo, 'web', 'src', 'lib', 'settings-page', 'settings-registry.ts'), 'utf8');
  const block = src.slice(src.indexOf('export const SETTINGS_SECTIONS'), src.indexOf('export type GroupId') > 0 ? src.indexOf('A titled GROUP') : undefined);
  const shipped = [...block.matchAll(/\{ id: '([a-z_]+)'/g)].map((m) => m[1]);
  assert.ok(shipped.length >= 10, `read ${shipped.length} sections from the registry`);
  assert.deepEqual([...SETTINGS_SECTIONS].sort(), [...shipped].sort());
});


test('findLinkInArgv returns only a carnivore link, never a switch or a path', () => {
  const exe = '/Applications/Carnivore.app/Contents/MacOS/Carnivore';
  assert.equal(findLinkInArgv([exe, 'carnivore://open']), 'carnivore://open');
  assert.equal(findLinkInArgv([exe]), null);
  assert.equal(findLinkInArgv([exe, '--inspect=9229', '--remote-debugging-port=1', '--js-flags=x', '--user-data-dir=/x', '/etc/passwd', 'ls']), null);
  assert.equal(findLinkInArgv([exe, '--inspect=9229', 'carnivore://settings/desktop', '--js-flags=x']), 'carnivore://settings/desktop');
  assert.equal(findLinkInArgv([exe, '--', 'carnivore://session/my-api']), 'carnivore://session/my-api');
  assert.equal(findLinkInArgv([exe, 'carnivore://open', 'carnivore://session/x']), 'carnivore://open', 'two links: the first wins');
  assert.equal(findLinkInArgv([exe, 'CARNIVORE://open']), 'CARNIVORE://open');
  assert.equal(findLinkInArgv([exe, '--carnivore://open', '-carnivore://open']), null, 'an argument starting with a dash is never a link');
  assert.equal(findLinkInArgv([null, 5, {}, ['carnivore://open']]), null);
  assert.equal(findLinkInArgv('carnivore://open'), null);
  assert.equal(findLinkInArgv(undefined), null);
});

test('handleSecondInstance reads the link and the exact --toggle, nothing else', () => {
  const exe = '/x/Carnivore';
  assert.deepEqual(handleSecondInstance([exe]), { focus: true, toggle: false, links: [] });
  assert.deepEqual(handleSecondInstance([exe, 'carnivore://open']), { focus: true, toggle: false, links: ['carnivore://open'] });
  assert.deepEqual(handleSecondInstance([exe, '--toggle']), { focus: true, toggle: true, links: [] });
  for (const near of ['--toggle=1', '--Toggle', '-toggle', 'toggle', '--toggle ']) {
    assert.equal(handleSecondInstance([exe, near]).toggle, false, near);
  }
  const hostile = handleSecondInstance([exe, '--inspect=9229', '--remote-debugging-port=1', '--user-data-dir=/x', '/bin/sh']);
  assert.deepEqual(hostile, { focus: true, toggle: false, links: [] });
  for (const bad of [null, undefined, 'carnivore://open', 7, {}]) assert.deepEqual(handleSecondInstance(bad), { focus: true, toggle: false, links: [] });
});


test('one focus per 500 ms: the second link inside the window is dropped, the first wins', () => {
  let now = 1000;
  const gate = createFocusGate({ now: () => now });
  assert.equal(gate.allow(), true);
  now += 100;
  assert.equal(gate.allow(), false);
  now += 399;
  assert.equal(gate.allow(), false, '499 ms after the first');
  now += 1;
  assert.equal(gate.allow(), true, '500 ms after the first');
  now += 100;
  assert.equal(gate.allow(), false, 'a drop does not restart the window');
  now += 400;
  assert.equal(gate.allow(), true);
});

test('a clock stepped back does not hold the gate closed (R2-BR-NOTES D2)', () => {
  let now = 10_000_000;
  const gate = createFocusGate({ now: () => now });
  assert.equal(gate.allow(), true);
  now -= 3_600_000;
  assert.equal(gate.allow(), true, 'the step back reads as open, not as a negative elapsed time');
  now += 100;
  assert.equal(gate.allow(), false, 'and the window then runs from the new reading');
});


function fakeWindow(up = true) {
  const calls = [];
  const target = {
    open: (hash) => { calls.push(['open', hash]); return up; },
    openApproval: (id) => { calls.push(['openApproval', id]); return up; },
  };
  const win = new Proxy(target, { get(t, prop) { if (prop in t) return t[prop]; throw new Error(`the router touched appWindow.${String(prop)}`); } });
  return { win, calls, setUp: (value) => { up = value; } };
}

function makeRouter(opts = {}) {
  const fake = fakeWindow(opts.up !== false);
  const clock = { now: 10_000 };
  const warnings = [];
  const router = createLinkRouter({ appWindow: fake.win, now: () => clock.now, warn: (...args) => warnings.push(args) });
  return { router, fake, clock, warnings };
}

test('the router opens a place and nothing else, for every accepted link', () => {
  for (const [link, want] of ACCEPTED) {
    const { router, fake } = makeRouter();
    assert.equal(router.handle(link).ok, true, link);
    const expected = want.kind === 'approvals' ? [['openApproval', want.approvalId]] : [['open', want.hash]];
    assert.deepEqual(fake.calls, expected, link);
  }
});

test('the router does nothing at all for a refused link, and logs it', () => {
  for (const [link] of REFUSED) {
    const { router, fake, warnings } = makeRouter();
    assert.equal(router.handle(link).ok, false, link);
    assert.deepEqual(fake.calls, [], `${JSON.stringify(link)} must not raise or open anything`);
    assert.equal(warnings.length, 1, link);
  }
  const { router, fake } = makeRouter();
  assert.equal(router.handle(undefined).ok, false);
  assert.deepEqual(fake.calls, []);
});

test('a refused link does not use up the focus window', () => {
  const { router, fake, clock } = makeRouter();
  router.handle('carnivore://bogus');
  clock.now += 10;
  assert.equal(router.handle('carnivore://open').ok, true);
  assert.equal(fake.calls.length, 1);
});

test('two links 100 ms apart yield one focus; the next at 600 ms yields another', () => {
  const { router, fake, clock } = makeRouter();
  router.handle('carnivore://session/one');
  clock.now += 100;
  assert.equal(router.handle('carnivore://session/two').ok, false);
  clock.now += 500;
  router.handle('carnivore://session/three');
  assert.deepEqual(fake.calls, [['open', 'session/one'], ['open', 'session/three']]);
});

test('a link that arrives before the window can open is held and replayed once, newest wins', () => {
  const { router, fake, clock } = makeRouter({ up: false });
  assert.equal(router.handle('carnivore://session/old').ok, true);
  clock.now += 600;
  router.handle('carnivore://settings/desktop');
  fake.calls.length = 0;
  fake.setUp(true);
  router.replay();
  assert.deepEqual(fake.calls, [['open', '#settings/desktop']]);
  router.replay();
  assert.equal(fake.calls.length, 1, 'replayed once');
});

test('a held link is dropped after 60 seconds', () => {
  const { router, fake, clock } = makeRouter({ up: false });
  router.handle('carnivore://open');
  clock.now += 60_001;
  fake.calls.length = 0;
  fake.setUp(true);
  router.replay();
  assert.deepEqual(fake.calls, []);
});

test('a link that fails again on replay stays held', () => {
  const { router, fake } = makeRouter({ up: false });
  router.handle('carnivore://approvals/ses_1');
  fake.calls.length = 0;
  router.replay();
  assert.deepEqual(fake.calls, [['openApproval', 'ses_1']]);
  fake.setUp(true);
  router.replay();
  assert.equal(fake.calls.length, 2);
});

test('navigation only: the link modules import nothing that can act, and the router exposes no way to call the API', () => {
  for (const file of ['deep-link.js', 'link-router.js']) {
    const src = fs.readFileSync(path.join(mac, file), 'utf8');
    const code = src.split('\n').filter((line) => !line.trim().startsWith('//') && !line.trim().startsWith('*')).join('\n');
    for (const banned of [/require\(\s*['"](node:)?(child_process|fs|net|http|https|dgram|dns|tls|os|vm|worker_threads|electron)['"]/,
      /openExternal/, /\bfetch\b/, /\bexec(File|Sync)?\(/, /\bspawn\(/, /loadURL/, /sendInput|sendKeys|dialog\/answer|getAuthed|sendAuthed|ipcMain|webContents/]) {
      assert.doesNotMatch(code, banned, `${file} must not use ${banned}`);
    }
  }
  const { router } = makeRouter();
  assert.deepEqual(Object.keys(router).sort(), ['handle', 'replay']);
});


function fakeShortcut({ refuse = [], throwOn = [] } = {}) {
  const live = new Set();
  const log = [];
  return {
    live, log,
    register(accelerator, callback) {
      log.push(['register', accelerator]);
      if (throwOn.includes(accelerator)) throw new TypeError('bad accelerator');
      if (refuse.includes(accelerator)) return false;
      live.add(accelerator);
      this.callbacks = { ...(this.callbacks || {}), [accelerator]: callback };
      return true;
    },
    unregister(accelerator) { log.push(['unregister', accelerator]); live.delete(accelerator); },
    isRegistered: (accelerator) => live.has(accelerator),
  };
}

function makeHotkey(shortcut, read) {
  const reports = [];
  const fired = [];
  const hotkey = createHotkey({
    globalShortcut: shortcut, readAccelerator: read, report: (status) => reports.push(status), onFire: () => fired.push(true),
  });
  return { hotkey, reports, fired };
}

test('hotkey: success reports registered with no error, and a press fires onFire', async () => {
  const shortcut = fakeShortcut();
  const { hotkey, reports, fired } = makeHotkey(shortcut, async () => 'Ctrl+Option+Cmd+C');
  await hotkey.refresh();
  assert.deepEqual(reports, [{ registered: true, error: null }]);
  shortcut.callbacks['Ctrl+Option+Cmd+C']();
  assert.equal(fired.length, 1);
});

test('hotkey: a refused registration reports registered false with a short reason', async () => {
  const shortcut = fakeShortcut({ refuse: ['Ctrl+Option+Cmd+C'] });
  const { hotkey, reports } = makeHotkey(shortcut, async () => 'Ctrl+Option+Cmd+C');
  await hotkey.refresh();
  assert.equal(reports.length, 1);
  assert.equal(reports[0].registered, false);
  assert.equal(typeof reports[0].error, 'string');
  assert.ok(reports[0].error.length > 0 && reports[0].error.length <= 60);
  assert.equal(reports[0].error, reports[0].error.toLowerCase());
});

test('hotkey: a one-modifier or system chord is never registered and says why (review A6)', async () => {
  for (const chord of ['Cmd+C', 'Cmd+V', 'Cmd+Space', 'Option+C', 'Cmd+Command+C', 'Cmd+Shift+Q', 'Cmd+Ctrl+Q', 'Command+Alt+Esc', 'Cmd+Shift+4']) {
    const shortcut = fakeShortcut();
    const { hotkey, reports } = makeHotkey(shortcut, async () => chord);
    await hotkey.refresh();
    assert.deepEqual(shortcut.log, [], `${chord} must not reach globalShortcut.register`);
    assert.equal(reports[0].registered, false, chord);
    assert.equal(reports[0].error, 'it would take a shortcut every app uses');
  }
  for (const chord of ['Ctrl+Option+Cmd+C', 'Cmd+Shift+K', 'Ctrl+F12', 'Cmd+F5']) assert.equal(isSafeAccelerator(chord), true, chord);
  const ok = fakeShortcut();
  await makeHotkey(ok, async () => 'Ctrl+Option+Cmd+C').hotkey.refresh();
  assert.deepEqual([...ok.live], ['Ctrl+Option+Cmd+C']);
});

test('hotkey: a thrown error from register is caught and reported', async () => {
  const shortcut = fakeShortcut({ throwOn: ['Ctrl+Option+Cmd+C'] });
  const { hotkey, reports } = makeHotkey(shortcut, async () => 'Ctrl+Option+Cmd+C');
  await assert.doesNotReject(hotkey.refresh());
  assert.equal(reports[0].registered, false);
  assert.equal(typeof reports[0].error, 'string');
});

test('hotkey: changing the accelerator unregisters the old one first; the same one is left alone', async () => {
  const shortcut = fakeShortcut();
  let value = 'Ctrl+Option+Cmd+C';
  const { hotkey, reports } = makeHotkey(shortcut, async () => value);
  await hotkey.refresh();
  await hotkey.refresh();
  assert.deepEqual(shortcut.log, [['register', 'Ctrl+Option+Cmd+C']], 'unchanged: no second register');
  value = 'Ctrl+Shift+K';
  await hotkey.refresh();
  assert.deepEqual(shortcut.log.slice(1), [['unregister', 'Ctrl+Option+Cmd+C'], ['register', 'Ctrl+Shift+K']]);
  assert.deepEqual([...shortcut.live], ['Ctrl+Shift+K']);
  assert.deepEqual(reports.at(-1), { registered: true, error: null });
});

test('hotkey: an empty accelerator registers nothing and reports off', async () => {
  const shortcut = fakeShortcut();
  let value = 'Ctrl+Shift+K';
  const { hotkey, reports } = makeHotkey(shortcut, async () => value);
  await hotkey.refresh();
  value = '';
  await hotkey.refresh();
  assert.deepEqual(shortcut.log, [['register', 'Ctrl+Shift+K'], ['unregister', 'Ctrl+Shift+K']]);
  assert.deepEqual(reports.at(-1), { registered: null, error: null });
  assert.equal(shortcut.live.size, 0);
});

test('hotkey: an unreadable preference keeps what is registered; with nothing registered and nothing stored it registers NOTHING (review finding 2)', async () => {
  const shortcut = fakeShortcut();
  let value = 'Ctrl+Shift+K';
  const { hotkey } = makeHotkey(shortcut, async () => value);
  await hotkey.refresh();
  value = null;
  await hotkey.refresh();
  assert.deepEqual([...shortcut.live], ['Ctrl+Shift+K']);

  const fresh = fakeShortcut();
  const second = makeHotkey(fresh, async () => { throw new Error('server not up'); });
  assert.equal(await second.hotkey.refresh(), false);
  assert.equal(fresh.live.size, 0);
  assert.deepEqual(second.reports, [], 'nothing registered, so nothing reported');
});

test('hotkey: a stored accelerator stands in until the first read, a read is saved, and an off preference stays off', async () => {
  const saved = [];
  const store = (stored) => ({ load: () => stored, save: (value) => saved.push(value) });
  const mk = (shortcut, read, stored) => createHotkey({
    globalShortcut: shortcut, readAccelerator: read, report: () => {}, onFire: () => {}, store: store(stored),
  });

  const down = fakeShortcut();
  await mk(down, async () => null, 'Ctrl+Shift+K').refresh();
  assert.deepEqual([...down.live], ['Ctrl+Shift+K'], 'server down: the last accelerator the owner had');
  assert.deepEqual(saved, [], 'a stored value is not written back');

  const off = fakeShortcut();
  await mk(off, async () => null, '').refresh();
  assert.equal(off.live.size, 0, 'server down: the stored "off" is honoured');

  const up = fakeShortcut();
  await mk(up, async () => 'Ctrl+Shift+J', 'Ctrl+Shift+K').refresh();
  assert.deepEqual([...up.live], ['Ctrl+Shift+J'], 'a successful read wins over the stored value');
  assert.deepEqual(saved, ['Ctrl+Shift+J'], 'and is saved for the next launch');
});

test('hotkey store: round-trips under a directory, refuses a damaged file and an over-long value', () => {
  const { createHotkeyStore } = require(path.join(mac, 'hotkey-store.js'));
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hotkey-store-'));
  try {
    const store = createHotkeyStore(() => dir);
    assert.equal(store.load(), null, 'nothing ever read');
    store.save('Ctrl+Shift+K');
    assert.equal(store.load(), 'Ctrl+Shift+K');
    store.save('');
    assert.equal(store.load(), '', 'off is a stored answer, not an absence');
    store.save('x'.repeat(65));
    assert.equal(store.load(), '', 'an over-long value is not saved');
    fs.writeFileSync(path.join(dir, 'desktop-hotkey.json'), '{not json');
    assert.equal(store.load(), null, 'a damaged file reads as nothing');
    assert.equal(createHotkeyStore(() => { throw new Error('no userData'); }).load(), null, 'no folder reads as nothing');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('hotkey: stop unregisters everything and a late refresh does not register again', async () => {
  const shortcut = fakeShortcut();
  const { hotkey } = makeHotkey(shortcut, async () => 'Ctrl+Shift+K');
  await hotkey.refresh();
  hotkey.stop();
  assert.equal(shortcut.live.size, 0);
  await hotkey.refresh();
  assert.equal(shortcut.live.size, 0);
});

test('the hotkey default is the one the preferences module ships', () => {
  const py = fs.readFileSync(path.join(repo, 'src', 'core', 'desktop_app', 'preferences.py'), 'utf8');
  const shipped = /DEFAULT_HOTKEY: str = "([^"]+)"/.exec(py)[1];
  const { DEFAULT_ACCELERATOR } = require(path.join(mac, 'hotkey.js'));
  assert.equal(DEFAULT_ACCELERATOR, shipped);
});


const { loadStatusLed } = require(path.join(mac, 'tray-menu', 'need-you.js'));
const { longestWaiting } = require(path.join(mac, 'tray-menu', 'longest-waiting.js'));
const { createPressAction } = require(path.join(mac, 'hotkey-action.js'));
const led = loadStatusLed(path.join(repo, 'client'));

const row = (id, status, lastActivity, extra = {}) => ({
  activity_status: status, tmux_session: `carnivore_${id}`, session: { id, last_activity: lastActivity }, ...extra,
});

test('longest waiting: the oldest local session that needs the owner, never a peer row or a working one', () => {
  const list = [
    row('ses_work', 'working', '2026-10-23T08:00:00Z'),
    row('ses_new', 'question', '2026-10-23T11:00:00Z'),
    row('ses_old', 'question', '2026-10-23T09:00:00Z'),
    row('remote:peer-a:x', 'question', '2026-10-23T07:00:00Z', { host_key: 'peer-a' }),
  ];
  assert.deepEqual(longestWaiting(list, led), { need: 'question', sessionId: 'ses_old', tmuxName: 'carnivore_ses_old' });
  assert.equal(longestWaiting([row('ses_work', 'working', '2026-10-23T08:00:00Z')], led), null);
  assert.equal(longestWaiting(null, led), null);
  assert.equal(longestWaiting(list, null), null);
  assert.equal(longestWaiting([null, 5, {}, { session: {} }], led), null);
});

test('hotkey press: focused window does nothing; a waiting question opens its approvals popup; otherwise the window comes forward', () => {
  const calls = [];
  const win = (focused, up = true) => ({
    isFocused: () => focused,
    open: (hash) => { calls.push(['open', hash]); return up; },
    openApproval: (id) => { calls.push(['openApproval', id]); return up; },
  });
  const activate = () => calls.push(['activate']);
  const question = { need: 'question', sessionId: 'ses_1', tmuxName: 'carnivore_ses_1' };
  const gate = { need: 'gate', sessionId: 'ses_2', tmuxName: 'carnivore_ses_2' };

  createPressAction({ appWindow: win(true), waiting: () => question, onActivate: activate })();
  assert.deepEqual(calls.splice(0), []);
  createPressAction({ appWindow: win(false), waiting: () => question, onActivate: activate })();
  assert.deepEqual(calls.splice(0), [['openApproval', 'ses_1']]);
  createPressAction({ appWindow: win(false), waiting: () => gate, onActivate: activate })();
  assert.deepEqual(calls.splice(0), [['open', 'session/carnivore_ses_2']]);
  createPressAction({ appWindow: win(false), waiting: () => null, onActivate: activate })();
  assert.deepEqual(calls.splice(0), [['activate']]);
  createPressAction({ appWindow: win(false, false), waiting: () => question, onActivate: activate })();
  assert.deepEqual(calls.splice(0), [['openApproval', 'ses_1'], ['activate']], 'no server URL: the Dock-click path takes over');
});


const { wireAppLinks } = require(path.join(mac, 'app-links.js'));

test('wiring: open-url navigates and is swallowed, a second launch opens its link or toggles, the pushed preference moves the hotkey, quit releases it', async () => {
  const handlers = {};
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'wiring-userdata-'));
  const app = { on: (name, fn) => { handlers[name] = fn; }, isReady: () => true, setAsDefaultProtocolClient: () => true, getPath: () => userData };
  const shortcut = fakeShortcut();
  const calls = [];
  const window = { open: (h) => { calls.push(['open', h]); return true; }, openApproval: (id) => { calls.push(['openApproval', id]); return true; }, isFocused: () => false };
  const activations = [];
  const statuses = [];
  const links = wireAppLinks({
    app, globalShortcut: shortcut, appWindow: window, trayMenu: () => ({ api: () => null, longestWaiting: () => null }),
    onActivate: () => activations.push(true), setHotkeyStatus: (s) => statuses.push(s),
  });

  let prevented = 0;
  handlers['open-url']({ preventDefault: () => { prevented += 1; } }, 'carnivore://session/my-api');
  assert.equal(prevented, 1);
  assert.deepEqual(calls.splice(0), [['open', 'session/my-api']]);

  handlers['open-url']({ preventDefault: () => {} }, 'carnivore://bogus');
  assert.deepEqual(calls, [], 'a refused link opens nothing');

  await new Promise((r) => setTimeout(r, 520));
  links.secondInstance(['/x/Carnivore', '--inspect=9229', 'carnivore://settings/desktop']);
  assert.deepEqual(calls.splice(0), [['open', '#settings/desktop']]);
  assert.equal(activations.length, 0, 'a link that opened a place needs no extra raise');

  links.secondInstance(['/x/Carnivore']);
  assert.equal(activations.length, 1, 'a plain second launch raises the window');

  links.secondInstance(['/x/Carnivore', '--toggle']);
  assert.equal(activations.length, 2, '--toggle runs the hotkey press: nobody waiting, so the window comes forward');

  links.start();
  await new Promise((r) => setImmediate(r));
  assert.equal(shortcut.live.size, 0, 'before the preferences are read nothing is registered, the default included');
  assert.deepEqual(statuses, [], 'and nothing is reported');
  links.onDesktopPrefs({ status: 'ok', data: { values: {} } });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual([...shortcut.live], ['Ctrl+Option+Cmd+C'], 'an absent field is the default, registered once it was read');
  assert.deepEqual(statuses.at(-1), { registered: true, error: null });

  links.onDesktopPrefs({ status: 'ok', data: { values: { desktop_hotkey: 'Ctrl+Shift+K' } } });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual([...shortcut.live], ['Ctrl+Shift+K'], 'the push moves the hotkey');
  links.onDesktopPrefs({ status: 'ok', data: { values: {} } });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual([...shortcut.live], ['Ctrl+Option+Cmd+C'], 'an absent field is the default');
  links.onDesktopPrefs({ status: 'ok', data: { values: { desktop_hotkey: '' } } });
  await new Promise((r) => setImmediate(r));
  assert.equal(shortcut.live.size, 0, 'empty is off');
  assert.deepEqual(statuses.at(-1), { registered: null, error: null });
  for (const bad of [null, undefined, { status: 'unknown' }, { status: 'ok', data: null }, { status: 'ok', data: { values: 'x' } }]) links.onDesktopPrefs(bad);
  await new Promise((r) => setImmediate(r));
  assert.equal(shortcut.live.size, 0, 'a failed or malformed read changes nothing');
  links.onDesktopPrefs({ status: 'ok', data: { values: { desktop_hotkey: 'Ctrl+Shift+K' } } });
  await new Promise((r) => setImmediate(r));

  handlers['will-quit']();
  assert.equal(shortcut.live.size, 0);
});

test('wiring: the last accelerator read is kept under userData, so a launch with the server down uses it', async () => {
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'wiring-store-'));
  const launch = () => {
    const app = { on: () => {}, isReady: () => true, setAsDefaultProtocolClient: () => true, getPath: () => userData };
    const shortcut = fakeShortcut();
    const links = wireAppLinks({
      app, globalShortcut: shortcut, appWindow: { open: () => true, openApproval: () => true, isFocused: () => false },
      trayMenu: () => null, onActivate: () => {}, setHotkeyStatus: () => {},
    });
    return { links, shortcut };
  };
  try {
    const first = launch();
    first.links.start();
    await new Promise((r) => setImmediate(r));
    assert.equal(first.shortcut.live.size, 0, 'a first launch with no read: nothing registered');
    first.links.onDesktopPrefs({ status: 'ok', data: { values: { desktop_hotkey: 'Ctrl+Shift+K' } } });
    await new Promise((r) => setImmediate(r));

    const second = launch();
    second.links.start();
    await new Promise((r) => setImmediate(r));
    assert.deepEqual([...second.shortcut.live], ['Ctrl+Shift+K'], 'the stored accelerator is registered');

    first.links.onDesktopPrefs({ status: 'ok', data: { values: { desktop_hotkey: '' } } });
    await new Promise((r) => setImmediate(r));
    const third = launch();
    third.links.start();
    await new Promise((r) => setImmediate(r));
    assert.equal(third.shortcut.live.size, 0, 'an owner who turned it off keeps it off, server or no server');
  } finally {
    fs.rmSync(userData, { recursive: true, force: true });
  }
});


const readRepo = (...parts) => fs.readFileSync(path.join(repo, ...parts), 'utf8');

test('finding 1: the page never adopts or creates for a deep link (the vitest in navigation.test.ts proves the behaviour)', () => {
  const nav = readRepo('web', 'src', 'lib', 'launchpad', 'navigation.ts');
  const body = nav.slice(nav.indexOf('export async function openProjectByName'), nav.indexOf('export async function selectProject'));
  assert.ok(body.length > 200, 'found the function');
  assert.doesNotMatch(body, /attachRunningSession\(/, 'openProjectByName must not call the adopt path');
  assert.doesNotMatch(body, /adoptSession/, 'and must not adopt');
});

test('finding 3: the docs say a link starts the app, and only the hotkey needs it running', () => {
  const doc = readRepo('docs', 'desktop-app.md');
  const links = doc.slice(doc.indexOf('## Links and the hotkey'));
  assert.doesNotMatch(links, /after Cmd-Q neither does anything/, 'the false sentence is gone');
  assert.match(links, /a link starts the app/i, 'the doc says a link starts the app when it is not running');
  const catalog = JSON.parse(readRepo('features', 'catalog', 'desktop-links-hotkey.json'));
  const howTo = catalog.how_to.join('\n');
  assert.doesNotMatch(howTo, /links and the hotkey do nothing/, 'the catalog no longer says links do nothing after quitting');
  assert.match(howTo, /link.*(starts|launches|opens) the app/i);
});

test('finding 4: nothing claims the page resolves a launcher project; the project verb is documented as an alias', () => {
  const header = readRepo('macOS', 'deep-link.js').slice(0, 2400);
  const doc = readRepo('docs', 'desktop-app.md');
  const links = doc.slice(doc.indexOf('## Links and the hotkey'), doc.indexOf('Everything else is refused'));
  for (const [name, text] of [['deep-link.js header', header], ['desktop-app.md table', links]]) {
    assert.doesNotMatch(text, /resolves a project first/i, `${name} must not say the page resolves a project first`);
    assert.doesNotMatch(text, /project first, then/i, `${name} must not say project first`);
    assert.match(text, /alias/i, `${name} says project is an alias of session`);
  }
});
