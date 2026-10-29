
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const A = require('../../macOS/auto-update.js');

let passes = 0, failures = 0;
async function test(name, fn) {
  try { await fn(); passes++; }
  catch (e) { failures++; console.error(`FAIL: ${name}\n  ${e.stack || e.message}`); }
}

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cloude-auto-update-'));
function cfg(obj, raw) {
  const p = path.join(dir, `c${Math.random().toString(36).slice(2)}.json`);
  fs.writeFileSync(p, raw !== undefined ? raw : JSON.stringify(obj));
  return p;
}

await test('no env and no config means the public default feed (Alex, 2026-10-22)', () => {
  const want = { url: A.DEFAULT_FEED_URL, source: 'default', error: null, channel: 'stable' };
  assert.equal(A.DEFAULT_FEED_URL, 'https://github.com/NyedisInc/CarnivoreAI/releases/latest/download');
  assert.deepEqual(A.selectFeed({ configPath: null, env: {} }), want);
  assert.deepEqual(A.selectFeed({ configPath: path.join(dir, 'missing.json'), env: {} }), want);
  assert.deepEqual(A.selectFeed({ configPath: cfg(null, '{not json'), env: {} }), want);
  assert.deepEqual(A.selectFeed({ configPath: cfg({ updates: 'x' }), env: {} }), want);
});

await test('auto_update is OFF unless config holds a literal true', () => {
  assert.equal(A.readAutoUpdate(null), false);
  assert.equal(A.readAutoUpdate(cfg(null, '{bad')), false);
  assert.equal(A.readAutoUpdate(cfg({ updates: {} })), false);
  assert.equal(A.readAutoUpdate(cfg({ updates: { auto_update: 'true' } })), false);
  assert.equal(A.readAutoUpdate(cfg({ updates: { auto_update: true } })), true);
});

await test('config feed_url is used, trailing slash trimmed', () => {
  const r = A.selectFeed({ configPath: cfg({ updates: { feed_url: ' https://u.example/app/ ' } }), env: {}, packaged: false });
  assert.deepEqual(r, { url: 'https://u.example/app', source: 'config', error: null, channel: 'dev' });
});

await test('env wins over config', () => {
  const r = A.selectFeed({
    configPath: cfg({ updates: { feed_url: 'https://cfg.example/x' } }),
    env: { [A.ENV_FEED_URL]: 'https://env.example/y' }, packaged: false
  });
  assert.equal(r.url, 'https://env.example/y');
  assert.equal(r.source, 'env');
});

await test('plain http is refused except on loopback; junk is refused', () => {
  assert.match(A.selectFeed({ packaged: false, env: { [A.ENV_FEED_URL]: 'http://u.example/x' } }).error, /https/);
  assert.equal(A.selectFeed({ packaged: false, env: { [A.ENV_FEED_URL]: 'http://127.0.0.1:9/x' } }).url, 'http://127.0.0.1:9/x');
  assert.equal(A.selectFeed({ packaged: false, env: { [A.ENV_FEED_URL]: 'ftp://u.example/x' } }).url, null);
  assert.match(A.selectFeed({ packaged: false, env: { [A.ENV_FEED_URL]: 'not a url' } }).error, /valid/);
});

function fake({ onCheck, onDownload } = {}) {
  const u = new EventEmitter();
  u.feeds = [];
  u.installs = 0;
  u.downloads = 0;
  u.downloadUpdate = async () => { u.downloads++; if (onDownload) await onDownload(u); };
  u.setFeedURL = (f) => u.feeds.push(f);
  u.quitAndInstall = () => { u.installs++; };
  u.checkForUpdates = async () => { if (onCheck) await onCheck(u); };
  return u;
}
function make(updater, feed, extra = {}) {
  const seen = [];
  const timers = [];
  const c = A.createUpdateController({
    updater, getFeed: () => feed.value, verifyUpdate: async () => ({ ok: true, reason: null }), onChange: (s) => seen.push(s.state), ...extra,
    setTimer: (fn, ms) => { timers.push({ fn, ms }); return timers.length - 1; },
    clearTimer: (i) => { if (timers[i]) timers[i].fn = null; timers[i] = null; }
  });
  return { c, seen, timers };
}
const GOOD = { url: 'https://u.example/app', source: 'env', error: null };

await test('no feed: not_configured, updater never touched', async () => {
  const u = fake();
  const { c } = make(u, { value: { url: null, source: 'none', error: null } });
  assert.equal((await c.check()).state, A.STATE_NOT_CONFIGURED);
  assert.equal(u.feeds.length, 0);
});

await test('refused feed is invalid_feed with the reason', async () => {
  const { c } = make(fake(), { value: { url: null, source: 'env', error: 'feed url must be https' } });
  const s = await c.check();
  assert.equal(s.state, A.STATE_INVALID_FEED);
  assert.match(s.detail, /https/);
});

await test('updater defaults: download no (auto update off), silent install on quit no', () => {
  const u = fake();
  make(u, { value: GOOD });
  assert.equal(u.autoDownload, false);
  assert.equal(u.autoInstallOnAppQuit, false);
  assert.equal(u.allowDowngrade, false);
});

await test('auto ON update path: checking, downloading, ready; install restarts once', async () => {
  const u = fake({ onCheck: (x) => {
    x.emit('checking-for-update');
    x.emit('update-available', { version: '1.14.1' });
    x.emit('download-progress', { percent: 41.6 });
    x.emit('update-downloaded', { version: '1.14.1' });
  } });
  const { c, seen } = make(u, { value: GOOD }, { getAutoUpdate: () => true });
  assert.equal(await c.install(), false, 'nothing to install yet');
  const s = await c.check();
  assert.equal(s.state, A.STATE_READY);
  assert.equal(s.version, '1.14.1');
  assert.deepEqual(seen, ['checking', 'downloading', 'downloading', 'ready']);
  assert.deepEqual(u.feeds, [{ provider: 'generic', url: 'https://u.example/app' }]);
  assert.equal(await c.install(), true);
  assert.equal(u.installs, 1);
  assert.match(A.stateLabel(c.getState()), /1\.14\.1 ready/);
});

await test('auto OFF: a found update waits as available, nothing downloads', async () => {
  const u = fake({ onCheck: (x) => { x.emit('checking-for-update'); x.emit('update-available', { version: '1.17.0' }); } });
  const { c, timers } = make(u, { value: GOOD });
  const s = await c.check();
  assert.equal(s.state, A.STATE_AVAILABLE);
  assert.equal(s.version, '1.17.0');
  assert.equal(u.downloads, 0);
  assert.equal(u.autoDownload, false);
  assert.equal(timers.length, 0, 'no quiet-install loop while auto update is off');
  assert.match(A.stateLabel(s), /1\.17\.0 available/);
});

await test('update now on an available update downloads, stops the server child, then restarts, in that order', async () => {
  const order = [];
  const u = fake({
    onCheck: (x) => x.emit('update-available', { version: '1.17.0' }),
    onDownload: (x) => { order.push('download'); x.emit('update-downloaded', { version: '1.17.0' }); }
  });
  u.quitAndInstall = () => { order.push('quitAndInstall'); u.installs++; };
  const { c } = make(u, { value: GOOD }, { beforeInstall: async () => { order.push('stop-server'); } });
  await c.check();
  assert.equal(await c.install(), true);
  assert.deepEqual(order, ['download', 'stop-server', 'quitAndInstall']);
  assert.equal(await c.install(), true, 'a second click while installing does nothing more');
  assert.equal(u.installs, 1);
});

await test('a server child that will not stop blocks the restart and lands in error', async () => {
  const u = fake({ onCheck: (x) => x.emit('update-downloaded', { version: '2.0.0' }) });
  const { c } = make(u, { value: GOOD }, { beforeInstall: async () => { throw new Error('server would not stop'); } });
  await c.check();
  assert.equal(await c.install(), false);
  assert.equal(u.installs, 0);
  assert.equal(c.getState().state, A.STATE_ERROR);
});

await test('auto ON: ready installs only at a quiet moment, rechecked each minute, never when busy or unknown', async () => {
  let quiet = false;
  const u = fake({ onCheck: (x) => x.emit('update-downloaded', { version: '1.17.0' }) });
  const { c, timers } = make(u, { value: GOOD }, { getAutoUpdate: () => true, isQuiet: () => quiet });
  await c.check();
  assert.equal(c.getState().state, A.STATE_READY);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, A.QUIET_RECHECK_MS);
  assert.equal(A.QUIET_RECHECK_MS, 60000);
  timers[0].fn();
  assert.equal(u.installs, 0);
  assert.equal(timers.length, 2);
  quiet = null;
  timers[1].fn();
  assert.equal(u.installs, 0);
  quiet = true;
  timers[2].fn();
  await new Promise((r) => setImmediate(r));
  assert.equal(u.installs, 1);
  assert.equal(timers.length, 3);
});

await test('auto OFF: a ready update never installs by itself and sets no quiet timer', async () => {
  const u = fake({ onCheck: (x) => x.emit('update-downloaded', { version: '1.17.0' }) });
  const { c, timers } = make(u, { value: GOOD }, { isQuiet: () => true });
  await c.check();
  assert.equal(timers.length, 0);
  assert.equal(u.installs, 0);
});

await test('turning auto ON downloads a waiting update; turning it OFF stops the quiet loop', async () => {
  const flag = { on: false };
  const u = fake({
    onCheck: (x) => x.emit('update-available', { version: '1.17.0' }),
    onDownload: (x) => x.emit('update-downloaded', { version: '1.17.0' })
  });
  const { c, timers } = make(u, { value: GOOD }, { getAutoUpdate: () => flag.on, isQuiet: () => false });
  await c.check();
  assert.equal(c.getState().state, A.STATE_AVAILABLE);
  flag.on = true;
  c.applyAutoUpdate();
  await new Promise((r) => setImmediate(r));
  assert.equal(u.downloads, 1);
  assert.equal(c.getState().state, A.STATE_READY);
  assert.equal(timers.filter(Boolean).length, 1, 'quiet loop armed');
  flag.on = false;
  c.applyAutoUpdate();
  assert.ok(timers.every((t) => t === null), 'quiet loop cancelled');
});

await test('a missing manifest (404) is the quiet unknown state, not an error; a 404 on the download is an error', async () => {
  const u = fake({ onCheck: (x) => {
    x.emit('checking-for-update');
    x.emit('error', Object.assign(new Error('Cannot find channel "latest-mac.yml" update info: HttpError: 404'), { code: 'ERR_UPDATER_CHANNEL_FILE_NOT_FOUND' }));
    throw new Error('Cannot find channel "latest-mac.yml" update info: HttpError: 404');
  } });
  const { c } = make(u, { value: GOOD });
  const s = await c.check();
  assert.equal(s.state, A.STATE_UNKNOWN);
  assert.equal(s.detail, null);
  assert.match(A.stateLabel(s), /no release information/);
  const u2 = fake({ onCheck: (x) => x.emit('update-available', { version: '1.17.0' }),
                    onDownload: () => { throw new Error('zip 404'); } });
  const m2 = make(u2, { value: GOOD });
  await m2.c.check();
  await m2.c.download();
  assert.equal(m2.c.getState().state, A.STATE_ERROR);
});

await test('up to date and failed check are different states', async () => {
  const mode = { v: 'current' };
  const u = fake({ onCheck: (x) => {
    x.emit('checking-for-update');
    if (mode.v === 'current') x.emit('update-not-available', {});
    else { x.emit('error', new Error('feed returned 404')); throw new Error('feed returned 404'); }
  } });
  const { c } = make(u, { value: GOOD });
  assert.equal((await c.check()).state, A.STATE_CURRENT);
  mode.v = 'fail';
  const s = await c.check();
  assert.equal(s.state, A.STATE_ERROR);
  assert.match(s.detail, /404/);
  assert.match(A.stateLabel(s), /check failed/);
  assert.equal(u.feeds.length, 1, 'feed set once for an unchanged url');
});

await test('a rejection with no error event still lands in error', async () => {
  const u = fake({ onCheck: () => { throw new Error('boom'); } });
  const { c } = make(u, { value: GOOD });
  const s = await c.check();
  assert.equal(s.state, A.STATE_ERROR);
  assert.equal(s.detail, 'boom');
});

await test('a downloaded update survives a later failed or empty check', async () => {
  const u = fake();
  const { c } = make(u, { value: GOOD });
  u.emit('update-downloaded', { version: '2.0.0' });
  u.emit('error', new Error('later failure'));
  u.emit('update-not-available', {});
  assert.equal(c.getState().state, A.STATE_READY);
  u.checkForUpdates = async () => { throw new Error('must not be called'); };
  assert.equal((await c.check()).state, A.STATE_READY);
});

await test('a changed feed url is applied on the next check', async () => {
  const u = fake({ onCheck: (x) => x.emit('update-not-available', {}) });
  const feed = { value: GOOD };
  const { c } = make(u, feed);
  await c.check();
  feed.value = { ...GOOD, url: 'https://other.example/app' };
  await c.check();
  assert.equal(u.feeds.length, 2);
  assert.equal(u.feeds[1].url, 'https://other.example/app');
});

await test('start schedules a launch check then a recurring one; stop cancels', async () => {
  const u = fake({ onCheck: (x) => x.emit('update-not-available', {}) });
  const { c, timers } = make(u, { value: GOOD });
  c.start();
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, A.LAUNCH_CHECK_DELAY_MS);
  timers[0].fn();
  assert.equal(timers[1].ms, A.CHECK_INTERVAL_MS);
  assert.ok(A.CHECK_INTERVAL_MS <= 6 * 3600 * 1000, 'a few times a day');
  c.stop();
  assert.ok(timers.every((t) => t === null));
});

const STABLE = 'https://github.com/NyedisInc/CarnivoreAI/releases/latest/download';
const BETA = 'https://github.com/NyedisInc/CarnivoreAI/releases/download/channel-beta';

await test('packaged: only the two exact feeds are accepted, everything else is refused', () => {
  assert.equal(A.DEFAULT_FEED_URL, STABLE);
  assert.equal(A.BETA_FEED_URL, BETA);
  const bad = [
    'https://evil.example/x', 'http://127.0.0.1:9/x', 'http://localhost:9/x',
    STABLE + '?x=1', STABLE + '#f', STABLE + '/x', STABLE + '/../x', BETA + '/x', BETA + '?x=1',
    'https://github.com/example-owner/example-repo/releases/latest/download',
    'https://github.com:443/NyedisInc/CarnivoreAI/releases/latest/download',
    'https://u:p@github.com/NyedisInc/CarnivoreAI/releases/latest/download',
    'https://github.com.evil.example/NyedisInc/CarnivoreAI/releases/latest/download',
    'http://github.com/NyedisInc/CarnivoreAI/releases/latest/download',
    'https://GITHUB.com/nyedisinc/carnivoreai/releases/latest/download'
  ];
  for (const raw of bad) {
    for (const how of ['env', 'config']) {
      const r = how === 'env'
        ? A.selectFeed({ env: { [A.ENV_FEED_URL]: raw }, packaged: true })
        : A.selectFeed({ configPath: cfg({ updates: { feed_url: raw } }), env: {}, packaged: true });
      assert.equal(r.url, null, `${how} ${raw} must be refused`);
      assert.ok(r.error, `${how} ${raw} names a reason`);
    }
  }
  assert.equal(A.selectFeed({ env: { [A.ENV_FEED_URL]: 'https://evil.example/x' } }).url, null);
  for (const [raw, channel, url] of [[STABLE, 'stable', STABLE], [STABLE + '/', 'stable', STABLE],
    [` ${BETA} `, 'beta', BETA], [BETA + '/', 'beta', BETA]]) {
    const r = A.selectFeed({ env: { [A.ENV_FEED_URL]: raw }, packaged: true });
    assert.deepEqual(r, { url, source: 'env', error: null, channel });
  }
  const c = A.selectFeed({ configPath: cfg({ updates: { feed_url: BETA } }), env: { [A.ENV_FEED_URL]: STABLE } });
  assert.equal(c.channel, 'stable', 'env picks between the two and wins over config');
  assert.equal(A.selectFeed({ configPath: cfg({ updates: { feed_url: BETA } }), env: {} }).channel, 'beta');
  const d = A.selectFeed({ env: { [A.ENV_FEED_URL]: 'http://127.0.0.1:9/x' }, packaged: false });
  assert.deepEqual(d, { url: 'http://127.0.0.1:9/x', source: 'env', error: null, channel: 'dev' });
});

await test('an update-proof build, and only it, accepts the loopback feed; nothing else widens (F9)', () => {
  const loop = ['http://127.0.0.1:9/x', 'http://localhost:51234/feed', 'http://127.0.0.1:8123', 'http://127.0.0.1:8123/'];
  const nope = ['https://evil.example/x', 'http://192.168.1.5:8000/', 'http://127.0.0.1/x', 'http://127.0.0.1:9/x?y=1',
    'http://127.0.0.1:9/x#f', 'http://u:p@127.0.0.1:9/x', 'http://127.0.0.1.evil.example:9/x', 'https://127.0.0.1:9/x',
    'http://127.0.0.1:99999/x', 'http://127.0.0.1:9/../x', 'http://[::1]:9/x', 'http://0.0.0.0:9/x', 'http://LOCALHOST:9/x',
    'http://127.0.0.1:9\\@evil.example/x', 'ftp://127.0.0.1:9/x'];
  for (const buildPurpose of ['release', 'vm-test', 'banana', null, undefined]) {
    for (const raw of loop) {
      const r = A.selectFeed({ env: { [A.ENV_FEED_URL]: raw }, packaged: true, buildPurpose });
      assert.equal(r.url, null, `${buildPurpose} must refuse ${raw}`);
      assert.equal(r.channel, null);
      assert.ok(r.error);
    }
  }
  for (const raw of loop) {
    for (const how of ['env', 'config']) {
      const r = how === 'env'
        ? A.selectFeed({ env: { [A.ENV_FEED_URL]: raw }, packaged: true, buildPurpose: 'update-proof' })
        : A.selectFeed({ configPath: cfg({ updates: { feed_url: raw } }), env: {}, packaged: true, buildPurpose: 'update-proof' });
      assert.equal(r.url, raw.replace(/\/+$/, ''), `${how} ${raw}`);
      assert.equal(r.error, null);
      assert.equal(r.channel, 'dev');
    }
  }
  for (const raw of nope) {
    const r = A.selectFeed({ env: { [A.ENV_FEED_URL]: raw }, packaged: true, buildPurpose: 'update-proof' });
    assert.equal(r.url, null, `update-proof must refuse ${raw}`);
    assert.ok(r.error);
  }
  assert.equal(A.selectFeed({ env: { [A.ENV_FEED_URL]: BETA }, packaged: true, buildPurpose: 'update-proof' }).channel, 'beta');
  assert.equal(A.selectFeed({ env: {}, packaged: true, buildPurpose: 'update-proof' }).channel, 'stable');
});

await test('createFeedSelector logs a loopback acceptance once with the purpose, and logs nothing otherwise', () => {
  const lines = [];
  const proof = A.createFeedSelector({ packaged: true, buildPurpose: 'update-proof', env: { [A.ENV_FEED_URL]: 'http://127.0.0.1:9/x' }, log: (m) => lines.push(m) });
  assert.equal(proof().url, 'http://127.0.0.1:9/x');
  assert.equal(proof().url, 'http://127.0.0.1:9/x');
  assert.equal(lines.length, 1);
  assert.match(lines[0], /update-proof/);
  assert.match(lines[0], /127\.0\.0\.1:9/);
  const rel = [];
  const release = A.createFeedSelector({ packaged: true, buildPurpose: 'release', env: { [A.ENV_FEED_URL]: 'http://127.0.0.1:9/x' }, log: (m) => rel.push(m) });
  assert.equal(release().url, null);
  const std = A.createFeedSelector({ packaged: true, buildPurpose: 'update-proof', env: {}, log: (m) => rel.push(m) });
  assert.equal(std().channel, 'stable');
  assert.equal(rel.length, 0);
});

await test('a refused packaged feed is invalid_feed and the updater never starts', async () => {
  const u = fake();
  const getFeed = () => A.selectFeed({ env: { [A.ENV_FEED_URL]: 'https://evil.example/x' }, packaged: true });
  const { c } = make(u, { value: getFeed() });
  const s = await c.check();
  assert.equal(s.state, A.STATE_INVALID_FEED);
  assert.equal(u.feeds.length, 0);
});

await test('the beta feed turns allowPrerelease on, the stable feed keeps it off', async () => {
  for (const [raw, want] of [[BETA, true], [STABLE, false]]) {
    const u = fake();
    const { c } = make(u, { value: A.selectFeed({ env: { [A.ENV_FEED_URL]: raw }, packaged: true }) });
    await c.check();
    assert.equal(u.allowPrerelease, want, raw);
    assert.equal(u.channel, undefined, 'the updater channel is never set (it would allow downgrades)');
    assert.equal(u.allowDowngrade, false);
  }
});

const macRequire = createRequire(new URL('../../macOS/package.json', import.meta.url));
const eu = macRequire.resolve('electron-updater');
const { AppUpdater } = macRequire('electron-updater/out/AppUpdater');
const semver = createRequire(eu)('semver');
async function offered(cur, latest) {
  return await AppUpdater.prototype.isUpdateAvailable.call({
    currentVersion: semver.parse(cur), allowDowngrade: false,
    isUpdateSupported: () => true, isUserWithinRollout: () => true
  }, { version: latest });
}

await test('offered versions: beta.1 sees beta.2 on channel-beta, not 1.16.3 on stable; 1.16.3 sees 2.0.0-beta.2', async () => {
  assert.equal(await offered('2.0.0-beta.1', '2.0.0-beta.2'), true);
  assert.equal(await offered('2.0.0-beta.1', '1.16.3'), false);
  assert.equal(await offered('1.16.3', '2.0.0-beta.2'), true);
  assert.equal(await offered('2.0.0', '2.0.0-beta.2'), false);
  assert.equal(await offered('2.0.0-beta.1', '2.0.0'), true);
});

await test('electron-updater 6.8.9 asks a generic feed for latest-mac.yml (the channel is the URL path)', async () => {
  const { GenericProvider } = macRequire('electron-updater/out/providers/GenericProvider');
  const asked = [];
  const p = new GenericProvider({ provider: 'generic', url: BETA },
    { channel: null, isAddNoCacheQuery: false },
    { platform: 'darwin', executor: {}, isUseMultipleRangeRequest: false });
  p.httpRequest = async (url) => { asked.push(url.href || String(url)); return 'version: 2.0.0-beta.2\nfiles: []\npath: x.zip\nsha512: x\nreleaseDate: 2026-01-01\n'; };
  assert.equal(p.channel, 'latest-mac');
  await p.getLatestVersion();
  assert.equal(asked[0], BETA + '/latest-mac.yml');
});

await test('finding 3 (B-REVIEW): the stable feed refuses a prerelease at every step, the beta feed accepts it', async () => {
  const STABLE = { url: A.DEFAULT_FEED_URL, source: 'default', error: null, channel: 'stable' };
  const BETAF = { url: A.BETA_FEED_URL, source: 'config', error: null, channel: 'beta' };
  for (const [feed, refused] of [[STABLE, true], [BETAF, false]]) {
    const u = fake();
    const { c } = make(u, { value: feed });
    await c.check();
    u.emit('update-available', { version: '2.0.0-beta.2' });
    assert.equal(c.getState().state === A.STATE_UPDATE_REFUSED, refused, 'update-available ' + feed.channel);
    const u2 = fake();
    const m2 = make(u2, { value: feed });
    u2.emit('update-downloaded', { version: '2.0.0-beta.2', downloadedFile: '/x/u.zip' });
    assert.equal(m2.c.getState().state === A.STATE_UPDATE_REFUSED, refused, 'update-downloaded ' + feed.channel);
    assert.equal(m2.c.getState().state === A.STATE_READY, !refused);
  }
  const u3 = fake();
  const f3 = { value: { ...GOOD, channel: 'beta' } };
  let stopped = 0;
  const m3 = make(u3, f3, { beforeInstall: async () => { stopped++; } });
  u3.emit('update-downloaded', { version: '2.0.0-beta.2', downloadedFile: '/x/u.zip' });
  f3.value = { ...GOOD, channel: 'stable' };
  assert.equal(await m3.c.install(), false);
  assert.equal(stopped + u3.installs, 0);
  assert.equal(m3.c.getState().state, A.STATE_UPDATE_REFUSED);
  const u4 = fake();
  const m4 = make(u4, { value: { ...GOOD, channel: 'stable' } });
  u4.emit('update-downloaded', { version: '2.0.0', downloadedFile: '/x/u.zip' });
  assert.equal(m4.c.getState().state, A.STATE_READY);
});

await test('a native install failure after quitAndInstall ends the install: engine restarted, installing cleared, window failed, try again works (#2482)', async () => {
  const { windowFacts } = require('../../macOS/update-window.js');
  const events = [];
  const u = fake({ onCheck: (x) => x.emit('update-downloaded', { version: '1.17.0' }) });
  u.quitAndInstall = () => { u.installs++; events.push('quitAndInstall'); u.emit('error', new Error('Code signature did not pass validation')); };
  const logs = [];
  const { c } = make(u, { value: GOOD }, {
    beforeInstall: async () => { events.push('stop-server'); },
    recoverEngine: async () => { events.push('engine-restarted'); },
    log: (m) => logs.push(m)
  });
  await c.check();
  assert.equal(await c.install(), true);
  await new Promise((r) => setImmediate(r));
  assert.deepEqual(events, ['stop-server', 'quitAndInstall', 'engine-restarted']);
  const s = c.getState();
  assert.equal(s.state, A.STATE_ERROR);
  assert.equal(s.phase, null);
  assert.match(s.detail, /Code signature/);
  assert.ok(logs.some((m) => /Code signature did not pass validation/.test(m)), 'the updater log names the error');
  const t = (k) => k;
  const facts = windowFacts(s, t);
  assert.equal(facts.phase, 'error');
  assert.equal(facts.retryLabel, 'menubar.update.window.retry');
  assert.match(facts.detail, /Code signature/);
  u.quitAndInstall = () => { u.installs++; events.push('quitAndInstall-2'); };
  assert.equal(await c.install(), true, 'try again runs the install again');
  assert.equal(u.installs, 2);
  assert.equal(events.includes('quitAndInstall-2'), true);
});

await test('beforeInstall throwing after the quit began starts the engine again and try again works (#2482 follow-up)', async () => {
  const events = [];
  const u = fake({ onCheck: (x) => x.emit('update-downloaded', { version: '1.17.0' }) });
  let fails = true;
  const { c } = make(u, { value: GOOD }, {
    beforeInstall: async () => { events.push('stop-server'); if (fails) throw new Error('the server did not stop'); },
    recoverEngine: async () => { events.push('engine-restarted'); }
  });
  await c.check();
  assert.equal(await c.install(), false);
  assert.deepEqual(events, ['stop-server', 'engine-restarted']);
  assert.equal(c.getState().state, A.STATE_ERROR);
  assert.equal(c.getState().phase, null);
  fails = false;
  assert.equal(await c.install(), true, 'try again installs the staged update');
  assert.equal(u.installs, 1);
});

fs.rmSync(dir, { recursive: true, force: true });
console.log(`${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
