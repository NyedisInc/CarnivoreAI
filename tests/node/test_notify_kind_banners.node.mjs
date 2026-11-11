import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const repo = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const banners = path.join(repo, 'macOS', 'banners');
const kind = require(path.join(banners, 'kind.js'));
const { createToastBanner } = require(path.join(banners, 'toast-banner.js'));
const { createCorner } = require(path.join(banners, 'corner.js'));
const { installNamedSounds } = require(path.join(banners, 'sounds.js'));
const { createPresenter } = require(path.join(banners, 'presenter-electron.js'));

function response(name) {
  const f = JSON.parse(fs.readFileSync(path.join(repo, 'tests', 'fixtures', 'notify_cards', `${name}.json`), 'utf8'));
  const p = f.payload;
  return { kind: p.kind, type: p.type, title: p.title, body: p.body, sub: p.sub, lv: p.lv, snd: p.snd, acts: p.acts, card: { ...f.card, ...(f.full || {}) }, ...(f.item ? { item: f.item } : {}) };
}

const EXPECT = {
  yesno: ['question on nostromo', 'carnivore-ask', false, [], 'type an answer', true],
  choice: ['pick one on nostromo', 'carnivore-ask', false, [], 'type an answer', true],
  permission: ['permission on studio', 'carnivore-ask', false, [], null, true],
  file: ['file on nostromo', 'carnivore-soft', false, ['open_file', 'save_file'], null, false],
  link: ['link on nostromo', 'carnivore-soft', false, ['open_link', 'copy_link'], null, false],
  image: ['image on studio', 'carnivore-soft', false, ['open', 'save'], null, true],
  video: ['video on nostromo', 'carnivore-soft', false, ['play', 'open'], null, true],
  finished: ['done on nostromo', 'carnivore-done', false, ['open'], 'reply', true],
  died: ['session died on studio', 'carnivore-alarm', false, ['reopen', 'open'], null, true],
  update: ['agent update on nostromo', undefined, true, ['restart_agents', 'later'], null, false],
  appupdate: ['app update', undefined, true, ['install', 'later'], null, false],
  swarm: ['from home on studio', 'carnivore-ask', false, ['pick.1', 'pick.2'], 'type an answer', true],
  crosstalk: ['crosstalk to home', 'carnivore-soft', false, [], 'reply', false],
  signin: ['claude account needs you', 'carnivore-alarm', false, ['sign_in'], null, true],
  notice: ['alert on nostromo', undefined, false, ['open'], null, false],
};

test('every one of the 15 kinds plans the expected banner', () => {
  assert.deepEqual(Object.keys(EXPECT).sort(), [...kind.KINDS].sort());
  for (const [name, [sub, sound, silent, ids, reply, corner]] of Object.entries(EXPECT)) {
    const plan = kind.planFromCard({ response: response(name) });
    assert.equal(plan.kind, name);
    assert.equal(plan.subtitle, sub, name);
    assert.equal(plan.sound, sound, name);
    assert.equal(plan.silent, silent, name);
    assert.deepEqual(plan.buttons.map((b) => b.id), ids, name);
    assert.equal(plan.reply, reply, name);
    assert.equal(plan.corner, corner, name);
    assert.ok(fs.existsSync(plan.icon) && plan.icon.endsWith(`icons/${name}.png`), `icon of ${name}`);
  }
});

test('the corner follows urgency and the local switch; an ask stays up, anything else hides', () => {
  assert.equal(kind.cornerWanted({ kind: 'notice', lv: 't' }), true);
  assert.equal(kind.cornerWanted({ kind: 'died', lv: 't', corner: false }), false);
  assert.equal(kind.cornerWanted({ kind: 'died', lv: 'p' }), false);
  assert.equal(kind.cornerWanted({ kind: 'finished', lv: 'a' }), true);
  assert.equal(kind.cornerWanted({ kind: 'link', lv: 'a' }), false);
  assert.equal(kind.planFromCard({ response: response('permission') }).autoHideMs, 0);
  assert.equal(kind.planFromCard({ response: response('finished') }).autoHideMs, kind.CORNER_HIDE_MS);
});

test('passive and none are silent, default names no sound, and the desktop column off posts nothing', () => {
  assert.deepEqual(kind.soundOptions('ask', 'p'), { silent: true });
  assert.deepEqual(kind.soundOptions('none', 't'), { silent: true });
  assert.deepEqual(kind.soundOptions('default', 'a'), { silent: false });
  assert.equal(kind.planFromCard({ response: response('notice'), desktopOn: false }).post, false);
  assert.equal(kind.planFromCard({ response: response('notice') }).post, true);
  const options = kind.bannerOptions(kind.planFromCard({ response: response('update') }), { image: (f) => f });
  assert.equal(options.silent, true);
  assert.equal('sound' in options, false);
});

test('the action order is the contract order and a cap drops only the tail', () => {
  const plan = kind.planFromCard({ response: response('video') });
  const options = kind.bannerOptions(plan, { id: 't1', groupId: 'ses_1', image: (f) => f });
  assert.deepEqual(options.actions.map((a) => a.text), ['play', 'open']);
  assert.equal(options.subtitle, 'video on nostromo');
  assert.equal(options.sound, 'carnivore-soft');
  assert.equal(options.id, 't1');
  const reply = kind.bannerOptions(kind.planFromCard({ response: response('finished') }), { image: (f) => f });
  assert.equal(reply.hasReply, true);
  assert.equal(reply.replyPlaceholder, 'reply');
});

function fakeNotification() {
  const posted = [];
  class N {
    constructor(options) { this.options = options; this.handlers = {}; this.closed = false; posted.push(this); }
    on(name, fn) { this.handlers[name] = fn; }
    show() { this.shown = true; }
    close() { this.closed = true; }
  }
  return { N, posted };
}

function fakeApi(card, extra = {}) {
  const calls = [];
  return {
    calls,
    getAuthed: async (route) => {
      calls.push(['GET', route]);
      if (route.includes('/cards/')) return extra.cardStatus ? { reachable: false, status: extra.cardStatus } : { reachable: true, data: card };
      if (route.endsWith('/settings')) return { reachable: true, data: { desktop: { [card.type]: { value: extra.desktop !== false } } } };
      if (route.endsWith('/styles')) return { reachable: true, data: { styles: { [card.type]: { corner: extra.corner } } } };
      if (route.startsWith('/api/v1/swarm/questions')) return { reachable: true, data: extra.questions || [] };
      return { reachable: true, data: { toasts: extra.toasts || [] } };
    },
    sendAuthed: async (route, body, method) => { calls.push([method, route, body]); return extra.write ? extra.write(route) : { reachable: true, data: {} }; },
  };
}

function build(card, extra = {}) {
  const { N, posted } = fakeNotification();
  const shownCorner = [];
  const api = fakeApi(card, extra);
  const opened = [];
  const toasts = createToastBanner({
    getApi: () => api, Notification: N, nativeImage: { createFromPath: (f) => ({ file: f }) }, isLocked: () => extra.locked === true, thumbs: extra.thumbs,
    shell: { openExternal: async (u) => { opened.push(u); } }, clipboard: { writeText: (t) => opened.push(`copy ${t}`) },
    corner: { show: async (c) => { shownCorner.push(c); return true; }, hide() {}, hideKey: (k) => shownCorner.push(`hide ${k}`) },
  });
  return { toasts, posted, shownCorner, api, opened };
}

test('a mirrored toast posts its kind banner and corner card, a reply goes through the crosstalk route', async () => {
  const card = response('finished');
  const { toasts, posted, shownCorner, api } = build(card);
  let opens = 0;
  const handled = await toasts.present({ title: 't', body: 'b', askSessionId: '', meta: { id: 'toast_1', session_id: 'ses_1', tmux_name: '' }, silent: false, open: () => { opens += 1; } });
  assert.equal(handled, true);
  assert.equal(posted.length, 1);
  assert.equal(posted[0].options.subtitle, 'done on nostromo');
  assert.equal(posted[0].options.sound, 'carnivore-done');
  assert.equal(posted[0].options.hasReply, true);
  assert.equal(shownCorner[0].key, 'toast_1');
  assert.equal(shownCorner[0].shown.kind, 'finished');
  posted[0].handlers.reply({ reply: '  ship it ' });
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(api.calls.at(-1), ['POST', '/api/v1/crosstalk/messages', { to: 'ses_1', text: 'ship it' }]);
  assert.equal(posted[0].closed, true, 'a reply that went through closes the banner');
  const again = build(card);
  await again.toasts.present({ title: 't', body: 'b', askSessionId: '', meta: { id: 'toast_2', session_id: 'ses_1', tmux_name: '' }, silent: false, open: () => { opens += 1; } });
  again.posted[0].handlers.action({ actionIndex: 0 });
  assert.equal(opens, 1);
  assert.equal(again.posted[0].closed, true);
});

test('the desktop column off, a 404 and a down server', async () => {
  const off = build(response('notice'), { desktop: false });
  assert.equal(await off.toasts.present({ meta: { id: 'a' }, open() {} }), true);
  assert.equal(off.posted.length, 0);
  const gone = build(response('notice'), { cardStatus: 404 });
  assert.equal(await gone.toasts.present({ meta: { id: 'a' }, open() {} }), true);
  assert.equal(gone.posted.length, 0);
  const down = build(response('notice'), { cardStatus: 503 });
  assert.equal(await down.toasts.present({ meta: { id: 'a' }, open() {} }), false);
  assert.equal(await off.toasts.present({ meta: { id: '' }, open() {} }), false);
});

test('a link banner opens or copies only an http(s) url; the corner switch off keeps the corner card away', async () => {
  const { toasts, posted, shownCorner, opened } = build(response('link'), { corner: false });
  await toasts.present({ meta: { id: 'l1', session_id: 'ses_1' }, open() {} });
  assert.equal(shownCorner.length, 0);
  posted[0].handlers.action({ actionIndex: 1 });
  assert.deepEqual(opened, ['copy https://carnivore.ai/preview']);
  posted[0].handlers.action({ actionIndex: 0 });
  assert.deepEqual(opened.at(-1), 'https://carnivore.ai/preview');
});

test('an ask gets its corner card from its toast and an option press is routed to the answer handler', async () => {
  const card = response('permission');
  const { toasts, shownCorner } = build(card, { toasts: [{ id: 'toast_9', session_id: 'ses_1' }, { id: 'x', session_id: 'ses_2' }] });
  const pressed = [];
  await toasts.cornerForAsk({ key: 'ses_1|fp', sessionId: 'ses_1', answer: (a) => pressed.push(a) });
  assert.equal(shownCorner[0].key, 'ses_1|fp');
  assert.equal(shownCorner[0].autoHideMs, 0);
  toasts.press('ses_1|fp', 'opt.2');
  assert.deepEqual(pressed, ['opt.2']);
});

function fakeWindowClass(log) {
  return class W {
    constructor(options) {
      this.options = options; this.destroyed = false; log.windows.push(this);
      this.webContents = {
        send: (...a) => log.sent.push(a), setWindowOpenHandler: (fn) => { log.openHandler = fn; }, on: (n, fn) => { log.wc[n] = fn; },
        executeJavaScript: async () => 123, insertCSS: async () => 1,
      };
    }
    setAlwaysOnTop(...a) { log.top = a; }
    setVisibleOnAllWorkspaces() {}
    on() {}
    loadURL(u) { log.urls.push(u); return Promise.resolve(); }
    setBounds(b) { log.bounds = b; }
    showInactive() { log.inactive = true; }
    show() { log.focusShow = true; }
    hide() { log.hidden = true; }
    isDestroyed() { return this.destroyed; }
    destroy() { this.destroyed = true; }
  };
}

test('the corner window is a same-origin, sandboxed, non-activating panel; presses come only from its own page', async () => {
  const log = { windows: [], sent: [], urls: [], wc: {} };
  const ipc = {};
  const presses = [];
  const corner = createCorner({
    BrowserWindow: fakeWindowClass(log), screen: { getPrimaryDisplay: () => ({ workArea: { x: 0, y: 25, width: 1440, height: 800 } }) },
    ipcMain: { on: (name, fn) => { ipc[name] = fn; } }, getUrl: () => 'http://127.0.0.1:5001/anything?x=1', partitionFor: (o) => `persist:${o}`,
    onPress: (key, id) => presses.push([key, id]), onClose: (key) => presses.push(['close', key]), setTimer: () => 7, clearTimer: () => {},
  });
  assert.equal(await corner.show({ key: 'k', shown: { kind: 'died', card: null, acts: [] }, autoHideMs: 15000 }), true);
  const w = log.windows[0];
  assert.equal(w.options.type, 'panel');
  assert.equal(w.options.focusable, false);
  assert.equal(w.options.transparent, true);
  assert.equal(w.options.frame, false);
  assert.deepEqual([w.options.webPreferences.sandbox, w.options.webPreferences.contextIsolation, w.options.webPreferences.nodeIntegration], [true, true, false]);
  assert.equal(w.options.webPreferences.partition, 'persist:http://127.0.0.1:5001');
  assert.deepEqual(log.urls, ['http://127.0.0.1:5001/static/notify-corner.html']);
  assert.equal(log.inactive, true);
  assert.equal(log.focusShow, undefined);
  assert.deepEqual(log.openHandler(), { action: 'deny' });
  assert.deepEqual(log.bounds, { x: 1440 - 380 - 12, y: 25 + 96, width: 380, height: 125 });
  assert.equal(log.sent[0][0], 'carnivore:corner-card');
  const own = { sender: w.webContents, senderFrame: { } };
  own.sender.mainFrame = own.senderFrame;
  ipc['carnivore:corner-press'](own, 'open');
  ipc['carnivore:corner-press']({ sender: {}, senderFrame: {} }, 'open');
  assert.deepEqual(presses, [['k', 'open']]);
  ipc['carnivore:corner-close'](own);
  assert.deepEqual(presses.at(-1), ['close', 'k']);
  assert.equal(corner.currentKey(), null);
  assert.equal(await createCorner({ ...{}, BrowserWindow: fakeWindowClass(log), screen: {}, ipcMain: { on() {} }, getUrl: () => null, partitionFor: () => '', onPress() {}, onClose() {} })
    .show({ key: 'x', shown: {}, autoHideMs: 0 }), false);
});

test('the named sounds copy once into ~/Library/Sounds for a dev run and never when packaged', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 's6-home-'));
  try {
    assert.deepEqual(installNamedSounds({ isPackaged: true, platform: 'darwin', home }), []);
    const first = installNamedSounds({ isPackaged: false, platform: 'darwin', home });
    assert.deepEqual(first.sort(), ['carnivore-alarm.aiff', 'carnivore-ask.aiff', 'carnivore-done.aiff', 'carnivore-soft.aiff']);
    assert.deepEqual(installNamedSounds({ isPackaged: false, platform: 'darwin', home }), []);
    assert.deepEqual(installNamedSounds({ isPackaged: false, platform: 'linux', home }), []);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
  const pkg = JSON.parse(fs.readFileSync(path.join(repo, 'macOS', 'package.json'), 'utf8'));
  assert.ok(pkg.build.extraResources.some((r) => r.from === 'sounds' && r.to === '.'), 'the bundle ships the sounds at Resources');
});

test('the presenter still draws the approval banner as before (no kind fields leak in)', () => {
  const { N, posted } = fakeNotification();
  const p = createPresenter({ Notification: N, onAction() {}, onClick() {} });
  p.show('k', { title: 't', body: 'b', buttons: [{ label: 'Yes' }] }, ['id']);
  assert.deepEqual(Object.keys(posted[0].options).sort(), ['actions', 'body', 'title']);
});

const tick = () => new Promise((r) => setTimeout(r, 5));

test('reopen, install and a swarm pick go through the main app UI routes, once, and a refusal opens the app', async () => {
  const died = build(response('died'));
  let opens = 0;
  await died.toasts.present({ meta: { id: 'd1', session_id: 'ses_1', tmux_name: 'carnivore_api' }, open: () => { opens += 1; } });
  assert.deepEqual(died.posted[0].options.actions.map((a) => a.text), ['reopen', 'open']);
  died.posted[0].handlers.action({ actionIndex: 0 });
  died.posted[0].handlers.action({ actionIndex: 0 });
  await tick();
  assert.deepEqual(died.api.calls.filter((c) => c[0] === 'POST'), [['POST', '/api/v1/sessions/respawn', { session_name: 'carnivore_api' }]]);
  assert.equal(opens, 0);
  assert.equal(died.posted[0].closed, true);

  const refused = build(response('died'), { write: () => ({ reachable: true, data: { ok: false } }) });
  await refused.toasts.present({ meta: { id: 'd2', session_id: 'ses_1', tmux_name: 'carnivore_api' }, open: () => { opens += 1; } });
  refused.posted[0].handlers.action({ actionIndex: 0 });
  await tick();
  assert.equal(opens, 1, 'a respawn the server did not do opens the app');

  const app = build(response('appupdate'));
  await app.toasts.present({ meta: { id: 'a1' }, open() {} });
  app.posted[0].handlers.action({ actionIndex: 0 });
  await tick();
  assert.deepEqual(app.api.calls.filter((c) => c[0] === 'POST'), [['POST', '/api/v1/app-update/install', undefined]]);

  const locked = build(response('appupdate'), { locked: true });
  await locked.toasts.present({ meta: { id: 'a2' }, open: () => { opens += 1; } });
  locked.posted[0].handlers.action({ actionIndex: 0 });
  await tick();
  assert.equal(locked.api.calls.filter((c) => c[0] === 'POST').length, 0, 'a locked screen never changes state');
  assert.equal(opens, 2);
});

test('a swarm pick and a typed answer go to the huddle item the owner card names, and a card with no item opens the app', async () => {
  const card = { ...response('swarm'), item: '526' };
  const swarm = build(card);
  await swarm.toasts.present({ meta: { id: 's1', session_id: 'ses_1' }, open() {} });
  assert.deepEqual(swarm.posted[0].options.actions.map((a) => a.text), ["pick home's", "pick api-docs'"]);
  assert.equal(swarm.posted[0].options.hasReply, true);
  assert.deepEqual(swarm.shownCorner[0].shown.acts.map((a) => a[0]), ['pick.1', 'pick.2', 'answer']);
  swarm.posted[0].handlers.action({ actionIndex: 1 });
  await tick();
  assert.deepEqual(swarm.api.calls.at(-1), ['POST', '/api/v1/cplugs/huddle/items/526/messages', { text: 'riskiest card first, so a failure shows early' }]);
  assert.equal(swarm.api.calls.some((c) => String(c[1]).includes('/swarm/questions')), false, 'the question is never matched by its text');
  const typed = build(card);
  await typed.toasts.present({ meta: { id: 's2', session_id: 'ses_1' }, open() {} });
  typed.posted[0].handlers.reply({ reply: ' both, in order ' });
  await tick();
  assert.deepEqual(typed.api.calls.at(-1), ['POST', '/api/v1/cplugs/huddle/items/526/messages', { text: 'both, in order' }]);
  for (const item of [undefined, '12; drop']) {
    let opens = 0;
    const bare = build({ ...response('swarm'), item });
    await bare.toasts.present({ meta: { id: 's3', session_id: 'ses_1' }, open: () => { opens += 1; } });
    bare.posted[0].handlers.action({ actionIndex: 0 });
    await tick();
    assert.equal(bare.api.calls.filter((c) => c[0] === 'POST').length, 0);
    assert.equal(opens, 1);
  }
});

test('the banner offers exactly what the server sent: a lone later stays, a restart the server sends is kept, and a dialog keeps its own options', () => {
  const plan = kind.planFromCard({ response: { ...response('update'), acts: [['later', 'later']] } });
  assert.deepEqual(plan.buttons.map((b) => b.id), ['later']);
  assert.deepEqual(plan.shown.acts.map((a) => a[0]), ['later']);
  const ruled = kind.planFromCard({ response: response('update') });
  assert.deepEqual(ruled.buttons.map((b) => b.id), ['restart_agents', 'later']);
  assert.deepEqual(ruled.shown.acts.map((a) => a[0]), ['restart_agents', 'later']);
  const ask = kind.planFromCard({ response: response('permission') });
  assert.ok(ask.shown.acts.length > 0 && ask.shown.acts.every((a) => /^opt\.\d$/.test(a[0]) || ['yes', 'no'].includes(a[0])), 'a dialog ask keeps its own options for answer.js');
});

const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const fakeImages = {
  createFromBuffer: (b) => ({ isEmpty: () => !b.equals(PNG), getSize: () => ({ width: 1 }), toPNG: () => PNG }),
  createFromPath: (f) => ({ file: f }),
};
const fakeFetch = (log, status = 200) => async (url, init) => {
  log.push([url, init.headers.Authorization]);
  return { status, ok: status === 200, headers: { get: () => String(PNG.length) }, arrayBuffer: async () => PNG };
};

test('image, video and file banners get the real picture through the owner media routes, cached 0600 and deleted on close', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'thumb-test-'));
  const id = 'ab'.repeat(16);
  const log = [];
  const { createThumbnails } = require(path.join(banners, 'thumbnail.js'));
  const thumbs = createThumbnails({ nativeImage: fakeImages, dir: path.join(dir, 'cache') });
  const api = { baseUrl: 'http://127.0.0.1:5001', ensureToken: async () => ({ token: 'tok' }), forgetToken() {}, fetchImpl: fakeFetch(log) };
  const base = { type: 'x', kind: 'image', acts: [], card: {}, media: { id, mime: 'image/png' } };
  const image = await thumbs.get(api, 't1', 'image', base);
  const video = await thumbs.get(api, 't2', 'video', { ...base, kind: 'video' });
  const withPoster = await thumbs.get(api, 't3', 'file', { ...base, card: { poster: true } });
  const noPoster = await thumbs.get(api, 't4', 'file', base);
  const other = await thumbs.get(api, 't5', 'finished', base);
  const evil = await thumbs.get(api, 't6', 'image', { ...base, media: { id: '../../etc/passwd' } });
  assert.deepEqual(log.map((l) => l[0]), [`http://127.0.0.1:5001/api/v1/notifications/media/${id}`, `http://127.0.0.1:5001/api/v1/notifications/media/${id}/poster`, `http://127.0.0.1:5001/api/v1/notifications/media/${id}/poster`]);
  assert.ok(log.every((l) => l[1] === 'Bearer tok'));
  assert.equal(noPoster, null);
  assert.equal(other, null);
  assert.equal(evil, null);
  assert.ok(video && withPoster);
  assert.equal(fs.statSync(image.file).mode & 0o777, 0o600);
  assert.equal(fs.statSync(path.dirname(image.file)).mode & 0o777, 0o700);
  assert.match(image.dataUrl, /^data:image\/png;base64,/);
  thumbs.release('t1');
  assert.equal(fs.existsSync(image.file), false);
  const old = new Date(Date.now() - 8 * 24 * 3600 * 1000);
  fs.utimesSync(video.file, old, old);
  await thumbs.get(api, 't7', 'image', base);
  assert.equal(fs.existsSync(video.file), false);
  const down = await thumbs.get({ ...api, fetchImpl: fakeFetch([], 404) }, 't8', 'image', base);
  assert.equal(down, null);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('a mirrored image banner wears the picture and its corner card gets it as mediaUrl; closing deletes the file', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'thumb-test-'));
  const { createThumbnails } = require(path.join(banners, 'thumbnail.js'));
  const thumbs = createThumbnails({ nativeImage: fakeImages, dir });
  const card = { ...response('image'), media: { id: 'cd'.repeat(16), mime: 'image/png' } };
  const { toasts, posted, shownCorner, api } = build(card, { thumbs });
  Object.assign(api, { baseUrl: 'http://127.0.0.1:5001', ensureToken: async () => ({ token: 'tok' }), forgetToken() {}, fetchImpl: fakeFetch([]) });
  await toasts.present({ meta: { id: 'i1', session_id: 'ses_1' }, open() {} });
  const file = posted[0].options.icon.file;
  assert.ok(file.startsWith(dir) && fs.existsSync(file));
  assert.match(shownCorner[0].shown.mediaUrl, /^data:image\/png;base64,/);
  toasts.close('i1');
  assert.equal(fs.existsSync(file), false);
  fs.rmSync(dir, { recursive: true, force: true });
});
