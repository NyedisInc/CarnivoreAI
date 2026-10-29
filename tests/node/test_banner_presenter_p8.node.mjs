import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const repo = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const mac = path.join(repo, 'macOS');
const model = require(path.join(mac, 'banners', 'model.js'));
const launch = require(path.join(mac, 'banners', 'launch.js'));
const { actionIndexOf, replyTextOf } = require(path.join(mac, 'banners', 'presenter-electron.js'));
const { createBanners } = require(path.join(mac, 'banners', 'index.js'));
const catalog = (await import(pathToFileURL(path.join(repo, 'client', 'js', 'i18n', 'catalog.en.js')).href)).default;
const format = await import(pathToFileURL(path.join(repo, 'client', 'js', 'i18n', 'format.js')).href);
const strings = require(path.join(mac, 'tray-menu', 'strings.js'));
const t = strings.createTranslator(catalog, (entry, params) => format.formatEntry(entry, params, 'en'));

const FP = 'a'.repeat(64);
const QFP = 'b'.repeat(64);
const flush = () => new Promise((r) => setImmediate(r));
const dialog = (extra = {}) => ({
  id: 'dlg:ses_1:aaaa', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'build bot', kind: 'permission',
  question: 'Do you want to proceed?', options: ['Yes', 'No'], multi_select: false, has_other: false, fingerprint: FP,
  summary: 'Bash: ls', questions: [], questions_fingerprint: null, questions_state: null, ...extra,
});
const typedOnly = (extra = {}) => dialog({ kind: 'other', options: [], has_other: true, question: 'What name should I use?', ...extra });
const multiAsk = () => dialog({
  kind: 'ask_user_question', question_total: 2, questions_fingerprint: QFP, questions_state: 'matched',
  questions: [1, 2].map((n) => ({ question: `Q${n}?`, multi_select: false, options: [{ label: `a${n}` }, { label: `b${n}` }] })),
});

function fakeNotification(history = []) {
  const made = [];
  const removed = [];
  class N {
    constructor(opts) { this.opts = opts; this.handlers = {}; made.push(this); }
    static isSupported() { return true; }
    static remove(id) { removed.push(id); }
    static async getHistory() { return history.map((id) => ({ id })); }
    on(name, fn) { this.handlers[name] = fn; return this; }
    show() { this.shown = true; }
    close() { this.closed = true; if (this.handlers.close) this.handlers.close({}); }
  }
  return { N, made, removed };
}

function fakeApi(state) {
  const posts = [];
  return {
    posts,
    api: {
      async getAuthed(route) {
        if (route === '/api/v1/preferences') return { reachable: true, data: { values: { desktop_banners: true } } };
        return state.items ? { reachable: true, data: { items: state.items } } : { reachable: false, data: null };
      },
      async sendAuthed(route, body) { posts.push({ route, body }); return state.post || { reachable: true, data: {} }; },
    },
  };
}

function setup({ items, post, history, locked = false, extra = {} }) {
  const fake = fakeNotification(history);
  const state = { items, post };
  const { api, posts } = fakeApi(state);
  const opened = [];
  const banners = createBanners({
    platform: 'darwin', getApi: () => api, Notification: fake.N, readPermission: () => 'allowed', t,
    isWindowFocused: () => false, openApproval: (id) => opened.push(id), isLocked: () => locked, ...extra,
  });
  return { fake, state, posts, opened, banners };
}

test('S1: the action index is read from details.actionIndex first, the deprecated second argument second, nothing else', () => {
  assert.equal(actionIndexOf([{ actionIndex: 2 }]), 2);
  assert.equal(actionIndexOf([{ actionIndex: 1 }, 5]), 1);
  assert.equal(actionIndexOf([{}, 3]), 3);
  assert.equal(actionIndexOf([3]), null, 'a bare first argument is not an index');
  assert.equal(actionIndexOf([{ actionIndex: '1' }]), null);
  assert.equal(replyTextOf([{ reply: 'hi' }]), 'hi');
  assert.equal(replyTextOf([{}, 'old']), 'old');
  assert.equal(replyTextOf([{}]), null);
  assert.equal(model.VISIBLE_ACTION_CAP, null, 'every option stays a button');
});

test('S2: only a typed-reply-only dialog gets hasReply; options, multi-select and multi-question asks do not', () => {
  const plan = (item) => model.planFor(item, { t });
  assert.equal(plan(typedOnly()).reply, true);
  assert.equal(plan(typedOnly()).buttons.length, 0);
  assert.equal(plan(dialog({ has_other: true })).reply, undefined, 'options plus an other row: no reply field yet (readout R-a)');
  assert.equal(plan(typedOnly({ multi_select: true })).reply, undefined);
  assert.equal(plan(multiAsk()).reply, undefined);
  assert.equal(plan(typedOnly({ has_other: false })).reply, undefined, 'no free-text row: open only');
});

test('S2: a reply posts a banner with hasReply and no actions; the reply is sent as choice.other with the fingerprint', async () => {
  const s = setup({ items: [typedOnly()] });
  await s.banners.onApprovals();
  assert.equal(s.fake.made.length, 1);
  const opts = s.fake.made[0].opts;
  assert.equal(opts.hasReply, true);
  assert.equal(opts.actions, undefined);
  s.fake.made[0].handlers.reply({ reply: '  blue  ' });
  await flush();
  assert.deepEqual(s.posts, [{ route: '/api/v1/sessions/ses_1/dialog/answer', body: { fingerprint: FP, choice: { other: 'blue' }, source: 'owner_banner' } }]);
  assert.equal(s.fake.made[0].closed, true);
});

test('S2: a reply over 2000 characters is refused with a visible notice and the banner comes back; 2000 is accepted', async () => {
  const s = setup({ items: [typedOnly()] });
  await s.banners.onApprovals();
  s.fake.made[0].handlers.reply({ reply: 'x'.repeat(2001) });
  await flush();
  assert.equal(s.posts.length, 0);
  const notice = s.fake.made.find((n) => n.opts.title === t('desktop.banner.title_too_long'));
  assert.ok(notice, 'a too-long notice was posted');
  assert.match(notice.opts.body, /2000/);
  const again = s.fake.made.filter((n) => n.opts.hasReply === true);
  assert.equal(again.length, 2, 'the reply banner was drawn again');
  again[1].handlers.reply({ reply: 'y'.repeat(2000) });
  await flush();
  assert.equal(s.posts.length, 1);
  assert.equal(s.posts[0].body.choice.other.length, 2000);
});

test('S2: a 409 on a reply closes the banner and posts "this question changed", no retry; a locked screen only opens the app', async () => {
  const stale = setup({ items: [typedOnly()], post: { reachable: false, status: 409 } });
  await stale.banners.onApprovals();
  stale.fake.made[0].handlers.reply({ reply: 'hi' });
  await flush();
  assert.equal(stale.posts.length, 1);
  assert.ok(stale.fake.made.some((n) => n.opts.title === t('desktop.banner.title_changed')));
  const locked = setup({ items: [typedOnly()], locked: true });
  await locked.banners.onApprovals();
  locked.fake.made[0].handlers.reply({ reply: 'hi' });
  await flush();
  assert.equal(locked.posts.length, 0);
  assert.deepEqual(locked.opened, ['ses_1']);
});

test('S3: groupId is the session id; a multi-question ask has none', async () => {
  const s = setup({ items: [dialog(), multiAsk({}), dialog({ session_id: 'ses_2', fingerprint: 'c'.repeat(64) })].map((i, n) => (n === 1 ? { ...i, session_id: 'ses_3', fingerprint: 'd'.repeat(64), questions_fingerprint: QFP } : i)) });
  await s.banners.onApprovals();
  const byId = Object.fromEntries(s.fake.made.map((n) => [n.opts.id.split('|')[0], n.opts]));
  assert.equal(byId.ses_1.groupId, 'ses_1');
  assert.equal(byId.ses_2.groupId, 'ses_2');
  assert.equal(byId.ses_3.groupId, undefined);
});

test('S4: the notification id is session, fingerprint, step, and decodes back', async () => {
  const s = setup({ items: [dialog()] });
  await s.banners.onApprovals();
  assert.equal(s.fake.made[0].opts.id, `ses_1|${FP}|0`);
  assert.deepEqual(model.decodeNotificationId(`ses_1|${FP}|0`), { sessionId: 'ses_1', fingerprint: FP, step: 0 });
  assert.equal(model.decodeNotificationId('random-uuid'), null);
});

test('S4: once per run, delivered banners of ours whose dialog is gone are removed; others are kept', async () => {
  const s = setup({ items: [dialog()], history: [`ses_1|${FP}|0`, `ses_9|${'e'.repeat(64)}|0`, 'not-ours'] });
  await s.banners.onApprovals();
  assert.deepEqual(s.fake.removed, [`ses_9|${'e'.repeat(64)}|0`]);
});

test('S4: a cold-launch reply waits for the engine, matches by fingerprint and answers; a miss is stale; a button only opens', async () => {
  const info = (text) => ({ identifier: `ses_1|${FP}|0`, actionIdentifier: 'x', ...(text ? { userText: text } : {}) });
  let sleeps = 0;
  const s = setup({ items: null, extra: { sleep: async () => { sleeps += 1; if (sleeps === 2) s.state.items = [typedOnly()]; }, coldStepMs: 10, coldWaitMs: 100, coldLockKnown: true } });
  const result = await s.banners.coldLaunch(info('blue'));
  assert.equal(result.outcome, 'answered');
  assert.equal(sleeps, 2);
  assert.equal(s.posts[0].body.choice.other, 'blue');
  assert.deepEqual(s.fake.removed, [`ses_1|${FP}|0`]);

  const gone = setup({ items: [typedOnly({ fingerprint: 'f'.repeat(64) })], extra: { coldLockKnown: true } });
  assert.equal((await gone.banners.coldLaunch(info('blue'))).outcome, 'stale');
  assert.equal(gone.posts.length, 0);
  assert.ok(gone.fake.made.some((n) => n.opts.title === t('desktop.banner.title_changed')));

  const button = setup({ items: [typedOnly()] });
  assert.equal((await button.banners.coldLaunch(info(null))).outcome, 'opened');
  assert.deepEqual(button.opened, ['ses_1']);
  assert.equal(button.posts.length, 0);

  const never = setup({ items: null, extra: { sleep: async () => {}, coldStepMs: 10, coldWaitMs: 30, coldLockKnown: true } });
  assert.equal((await never.banners.coldLaunch(info('hi'))).outcome, 'failed');
  assert.equal((await never.banners.coldLaunch({ identifier: 'foreign' })).outcome, 'ignored');
});

test('P8-FIX B1: a cold-launch reply with a fresh lock tracker sends no POST and only opens the approval', async () => {
  const s = setup({ items: [typedOnly()] });
  const result = await s.banners.coldLaunch({ identifier: `ses_1|${FP}|0`, actionIdentifier: 'x', userText: 'blue' });
  assert.equal(result.outcome, 'opened');
  assert.equal(s.posts.length, 0);
  assert.deepEqual(s.opened, ['ses_1']);
});

test('P8-FIX S1: the engine wait is real time, so a slow readItems cannot stretch it past the deadline', async () => {
  let clock = 0;
  let reads = 0;
  const cold = launch.createColdLaunch({
    readItems: async () => { reads += 1; clock += 60000; return null; }, entries: new Map(), makeEntry: () => ({}), answerer: { reply: async () => ({}) },
    notice: () => {}, openApproval: () => {}, removeDelivered: () => {}, sleep: async () => {}, now: () => clock, coldLockKnown: true,
  });
  const result = await cold.handle({ identifier: `ses_1|${FP}|0`, userText: 'hi' });
  assert.equal(result.outcome, 'failed');
  assert.equal(reads, 2, 'two 60 s reads exhaust a 90 s wait; step counting would have read 30 times');
});

test('P8-FIX S3: a reply holding a control character is refused with a visible notice, no POST, and the banner comes back', async () => {
  const s = setup({ items: [typedOnly()] });
  await s.banners.onApprovals();
  s.fake.made[0].handlers.reply({ reply: 'two\nlines' });
  await flush();
  assert.equal(s.posts.length, 0);
  assert.ok(s.fake.made.some((n) => n.opts.title === t('desktop.banner.title_bad_chars')), 'a refusal notice was posted');
  assert.equal(s.fake.made.filter((n) => n.opts.hasReply === true).length, 2, 'the reply banner was drawn again');
  s.fake.made.filter((n) => n.opts.hasReply === true)[1].handlers.reply({ reply: 'del\u007fchar' });
  await flush();
  assert.equal(s.posts.length, 0);
});

test('S4: capture keeps the ready event launchInfo once', () => {
  let handler;
  launch.capture({ once: (name, fn) => { assert.equal(name, 'ready'); handler = fn; } });
  handler({}, { identifier: 'x' });
  assert.deepEqual(launch.take(), { identifier: 'x' });
  assert.equal(launch.take(), null);
});

test('banners off: an approvals pass makes no Notification call that could raise the macOS permission prompt (#2486)', async () => {
  const calls = [];
  class Spy {
    constructor() { calls.push('new'); }
    static isSupported() { return true; }
    static remove() { calls.push('remove'); }
    static async getHistory() { calls.push('getHistory'); return []; }
    on() { return this; }
    show() { calls.push('show'); }
    close() { calls.push('close'); }
  }
  const api = {
    async getAuthed(route) {
      if (route === '/api/v1/preferences') return { reachable: true, data: { values: { desktop_banners: false } } };
      return { reachable: true, data: { items: [dialog()] } };
    },
  };
  const banners = createBanners({
    platform: 'darwin', getApi: () => api, Notification: Spy, readPermission: () => 'unknown', t,
    isWindowFocused: () => false, openApproval: () => {},
  });
  await banners.onApprovals();
  assert.deepEqual(calls, [], 'no getHistory, remove, new or show while banners are off');
});

test('banners on: the once-per-run prune still reads the delivered banners (#2486)', async () => {
  const { fake, banners } = setup({ items: [dialog()], history: [] });
  let history = 0;
  fake.N.getHistory = async () => { history += 1; return []; };
  await banners.onApprovals();
  assert.equal(history, 1);
});
