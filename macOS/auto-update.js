'use strict';


const fs = require('node:fs');
const semver = require('semver');

const { PROOF_PURPOSE } = require('./proof-marker');
const ENV_FEED_URL = 'CARNIVORE_UPDATE_FEED_URL';
const DEFAULT_FEED_URL = 'https://github.com/NyedisInc/CarnivoreAI/releases/latest/download';
const BETA_FEED_URL = 'https://github.com/NyedisInc/CarnivoreAI/releases/download/channel-beta';
const QUIET_RECHECK_MS = 60 * 1000;
const LAUNCH_CHECK_DELAY_MS = 30 * 1000;
const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000;

const STATE_NOT_CONFIGURED = 'not_configured';
const STATE_INVALID_FEED = 'invalid_feed';
const STATE_IDLE = 'idle';
const STATE_CHECKING = 'checking';
const STATE_AVAILABLE = 'available';
const STATE_UNKNOWN = 'unknown';
const STATE_DOWNLOADING = 'downloading';
const STATE_READY = 'ready';
const STATE_CURRENT = 'current';
const STATE_ERROR = 'error';
const STATE_UPDATE_REFUSED = 'update_refused';

function readUpdatesBlock(configPath) {
  if (!configPath) return {};
  let data;
  try {
    data = JSON.parse(fs.readFileSync(configPath, 'utf-8'));
  } catch {
    return {};
  }
  const updates = data && data.updates;
  return updates && typeof updates === 'object' ? updates : {};
}

function readConfiguredFeed(configPath) {
  const url = readUpdatesBlock(configPath).feed_url;
  return typeof url === 'string' ? url.trim() : '';
}

function readAutoUpdate(configPath) {
  return readUpdatesBlock(configPath).auto_update === true;
}

function isMissingManifest(err) {
  const text = `${(err && err.code) || ''} ${(err && err.message) || err || ''}`;
  return /ERR_UPDATER_CHANNEL_FILE_NOT_FOUND|Cannot find channel|latest[-\w]*\.yml.*(404|not found)/i.test(text);
}

/* <path> */
function isLoopbackFeed(url) {
  const m = /^http:\/\/(?:127\.0\.0\.1|localhost):(\d{1,5})((?:\/[\w.~-]+)*)$/.exec(url);
  return m !== null && Number(m[1]) >= 1 && Number(m[1]) <= 65535 && !m[2].split('/').includes('..');
}

function createFeedSelector({ configPath = () => null, env, packaged, buildPurpose = null, log = () => {} }) {
  let announced = false;
  return () => {
    const feed = selectFeed({ configPath: configPath(), env, packaged, buildPurpose });
    if (feed.channel === 'dev' && packaged && !announced) {
      announced = true;
      log(`[auto-update] loopback feed ${feed.url} accepted for a ${buildPurpose} build`);
    }
    return feed;
  };
}

/* <path> */
function selectFeed({ configPath, env, packaged = true, buildPurpose = null } = {}) {
  const e = env || process.env;
  const fromEnv = typeof e[ENV_FEED_URL] === 'string' ? e[ENV_FEED_URL].trim() : '';
  const configured = fromEnv || readConfiguredFeed(configPath);
  const raw = configured || DEFAULT_FEED_URL;
  const source = fromEnv ? 'env' : (configured ? 'config' : 'default');
  const url = raw.replace(/\/+$/, '');
  if (packaged) {
    if (url === DEFAULT_FEED_URL) return { url, source, error: null, channel: 'stable' };
    if (url === BETA_FEED_URL) return { url, source, error: null, channel: 'beta' };
    if (buildPurpose === PROOF_PURPOSE && isLoopbackFeed(url)) return { url, source, error: null, channel: 'dev' };
    return { url: null, source, error: 'feed url must be one of the two release feeds of NyedisInc/CarnivoreAI', channel: null };
  }
  let u;
  try {
    u = new URL(raw);
  } catch {
    return { url: null, source, error: 'feed url is not a valid url', channel: null };
  }
  const loopback = u.hostname === '127.0.0.1' || u.hostname === 'localhost';
  if (u.protocol !== 'https:' && !(u.protocol === 'http:' && loopback)) {
    return { url: null, source, error: 'feed url must be https (http only on loopback)', channel: null };
  }
  return { url, source, error: null, channel: url === BETA_FEED_URL ? 'beta' : (url === DEFAULT_FEED_URL ? 'stable' : 'dev') };
}

function createUpdateController({
  updater, getFeed, getAutoUpdate = () => false, isQuiet = () => null, verifyUpdate = async () => ({ ok: false, reason: 'no update verifier configured' }),
  beforeInstall = async () => {}, recoverEngine = async () => {},
  onChange, setTimer = setTimeout, clearTimer = clearTimeout, log = () => {}
}) {
  let state = { state: STATE_IDLE, version: null, percent: null, checkedAt: null, detail: null, phase: null };
  let feedUrl = null;
  let timers = [];
  let quietTimer = null;
  let installing = false;
  let installFailed = false;
  let downloadWaiters = [];
  let stagedFile = null;

  const set = (patch) => {
    state = { ...state, ...patch };
    if (typeof onChange === 'function') onChange(state);
    if (state.state === STATE_READY) armQuietInstall(); else disarmQuietInstall();
  };

  updater.autoDownload = getAutoUpdate();
  updater.autoInstallOnAppQuit = false;
  updater.allowDowngrade = false;
  updater.allowPrerelease = false;

  updater.on('checking-for-update', () => {
    if (state.state !== STATE_READY && state.state !== STATE_DOWNLOADING) set({ state: STATE_CHECKING, detail: null });
  });
  const prereleaseOnStable = (version) =>
    getFeed().channel === 'stable' && typeof version === 'string' && semver.prerelease(version) !== null;
  const refusePrerelease = (version) => {
    log('[auto-update] refused prerelease ' + version + ' on the stable feed');
    set({ state: STATE_UPDATE_REFUSED, version, percent: null, detail: `prerelease ${version} on the stable feed`, checkedAt: Date.now() });
  };

  updater.on('update-available', (info) => {
    if (state.state === STATE_READY || state.state === STATE_DOWNLOADING) return;
    const version = (info && info.version) || null;
    if (prereleaseOnStable(version)) { refusePrerelease(version); return; }
    if (updater.autoDownload) set({ state: STATE_DOWNLOADING, version, percent: 0, checkedAt: Date.now() });
    else set({ state: STATE_AVAILABLE, version, percent: null, checkedAt: Date.now() });
  });
  updater.on('download-progress', (p) => {
    if (state.state === STATE_DOWNLOADING) {
      set({ percent: Math.round((p && p.percent) || 0) });
    }
  });
  updater.on('update-not-available', () => {
    if (state.state !== STATE_READY && state.state !== STATE_DOWNLOADING) {
      set({ state: STATE_CURRENT, version: null, percent: null, checkedAt: Date.now() });
    }
  });
  updater.on('update-downloaded', (info) => {
    if (prereleaseOnStable(info && info.version)) { refusePrerelease(info.version); return; }
    stagedFile = (info && info.downloadedFile) || null;
    set({ state: STATE_READY, version: (info && info.version) || state.version, percent: 100,
          checkedAt: Date.now(), detail: null });
    const waiters = downloadWaiters;
    downloadWaiters = [];
    waiters.forEach((w) => w(true));
  });
  updater.on('error', (err) => fail(err));

  async function failInstall(err) {
    const detail = (err && err.message) || String(err);
    log('[auto-update] native install failed after the restart request: ' + detail);
    installing = false;
    installFailed = true;
    set({ state: STATE_ERROR, phase: null, detail, checkedAt: Date.now() });
    try {
      await recoverEngine();
    } catch (recoverErr) {
      log('[auto-update] could not start the engine after the failed install: ' + ((recoverErr && recoverErr.message) || String(recoverErr)));
    }
  }

  function fail(err) {
    if (installing && state.phase === 'restarting') { failInstall(err); return; }
    if (state.state === STATE_READY) return;
    if (state.state !== STATE_DOWNLOADING && isMissingManifest(err)) {
      log('[auto-update] no release manifest at the feed yet');
      set({ state: STATE_UNKNOWN, version: null, percent: null, checkedAt: Date.now(), detail: null });
      return;
    }
    set({ state: STATE_ERROR, detail: (err && err.message) || String(err), checkedAt: Date.now() });
    const waiters = downloadWaiters;
    downloadWaiters = [];
    waiters.forEach((w) => w(false));
  }

  async function check() {
    if (state.state === STATE_READY || state.state === STATE_CHECKING ||
        state.state === STATE_DOWNLOADING) {
      return state;
    }
    const feed = getFeed();
    if (feed.error) {
      set({ state: STATE_INVALID_FEED, detail: feed.error });
      return state;
    }
    if (!feed.url) {
      set({ state: STATE_NOT_CONFIGURED, detail: null });
      return state;
    }
    try {
      if (feed.url !== feedUrl) {
        updater.setFeedURL({ provider: 'generic', url: feed.url });
        feedUrl = feed.url;
      }
      updater.autoDownload = getAutoUpdate();
      updater.allowPrerelease = feed.channel === 'beta';
      await updater.checkForUpdates();
    } catch (err) {
      if (state.state !== STATE_ERROR && state.state !== STATE_UNKNOWN) fail(err);
    }
    return state;
  }

  async function download() {
    if (state.state === STATE_READY) return true;
    if (state.state === STATE_AVAILABLE) {
      set({ state: STATE_DOWNLOADING, percent: 0 });
      try {
        await updater.downloadUpdate();
      } catch (err) {
        fail(err);
      }
      return state.state === STATE_READY;
    }
    if (state.state === STATE_DOWNLOADING) return new Promise((resolve) => downloadWaiters.push(resolve));
    return false;
  }

  async function install() {
    if (installing) return true;
    if (installFailed) { installFailed = false; set({ state: STATE_READY, detail: null }); }
    if (state.state !== STATE_READY && !(await download())) return false;
    if (prereleaseOnStable(state.version)) { refusePrerelease(state.version); return false; }
    installing = true;
    disarmQuietInstall();
    set({ phase: 'verifying' });
    let verdict;
    try {
      verdict = await verifyUpdate(stagedFile);
    } catch (err) {
      verdict = { ok: false, reason: (err && err.message) || String(err) };
    }
    if (!verdict || verdict.ok !== true) {
      installing = false;
      log('[auto-update] update refused: ' + (verdict && verdict.reason));
      set({ state: STATE_UPDATE_REFUSED, phase: null, detail: (verdict && verdict.reason) || 'update check failed', checkedAt: Date.now() });
      return false;
    }
    log('[auto-update] restarting to install ' + state.version);
    try {
      set({ phase: 'installing' });
      await beforeInstall();
      set({ phase: 'restarting' });
      updater.quitAndInstall();
    } catch (err) {
      installing = false;
      installFailed = true;
      set({ state: STATE_ERROR, phase: null, detail: (err && err.message) || String(err), checkedAt: Date.now() });
      try { await recoverEngine(); } catch (recoverErr) {
        log('[auto-update] could not start the engine after the failed install: ' + ((recoverErr && recoverErr.message) || String(recoverErr)));
      }
      return false;
    }
    return true;
  }

  function quietTick() {
    quietTimer = null;
    if (state.state !== STATE_READY || installing || !getAutoUpdate()) return;
    if (isQuiet() === true) install();
    else armQuietInstall();
  }

  function armQuietInstall() {
    if (quietTimer !== null || installing || state.state !== STATE_READY || !getAutoUpdate()) return;
    quietTimer = setTimer(quietTick, QUIET_RECHECK_MS);
  }

  function disarmQuietInstall() {
    if (quietTimer !== null) clearTimer(quietTimer);
    quietTimer = null;
  }

  function applyAutoUpdate() {
    const on = getAutoUpdate();
    updater.autoDownload = on;
    if (!on) {
      disarmQuietInstall();
    } else if (state.state === STATE_AVAILABLE) {
      download();
    } else if (state.state === STATE_READY) {
      armQuietInstall();
    }
    if (typeof onChange === 'function') onChange(state);
  }

  function start() {
    stop();
    const tick = () => {
      check();
      timers.push(setTimer(tick, CHECK_INTERVAL_MS));
    };
    timers.push(setTimer(tick, LAUNCH_CHECK_DELAY_MS));
  }

  function stop() {
    for (const t of timers) clearTimer(t);
    timers = [];
    disarmQuietInstall();
  }

  const isAutoUpdate = () => getAutoUpdate() === true;

  return { getState: () => state, isAutoUpdate, check, download, install, applyAutoUpdate, start, stop };
}

function stateLabel(s) {
  switch (s.state) {
    case STATE_NOT_CONFIGURED: return 'updates: no feed configured';
    case STATE_AVAILABLE: return `updates: ${s.version} available`;
    case STATE_UNKNOWN: return 'updates: no release information yet';
    case STATE_INVALID_FEED: return `updates: feed refused (${s.detail})`;
    case STATE_CHECKING: return 'updates: checking...';
    case STATE_DOWNLOADING: return `updates: downloading ${s.version || ''} ${s.percent || 0}%`.replace('  ', ' ');
    case STATE_READY: return `updates: ${s.version} ready`;
    case STATE_CURRENT: return 'updates: up to date';
    case STATE_UPDATE_REFUSED: return `updates: update refused (${s.detail})`;
    case STATE_ERROR: return `updates: check failed (${s.detail})`;
    default: return 'updates: not checked yet';
  }
}

module.exports = {
  ENV_FEED_URL, DEFAULT_FEED_URL, BETA_FEED_URL, LAUNCH_CHECK_DELAY_MS, CHECK_INTERVAL_MS, QUIET_RECHECK_MS,
  STATE_NOT_CONFIGURED, STATE_INVALID_FEED, STATE_IDLE, STATE_CHECKING, STATE_AVAILABLE,
  STATE_DOWNLOADING, STATE_READY, STATE_CURRENT, STATE_UNKNOWN, STATE_ERROR,
  STATE_UPDATE_REFUSED,
  readConfiguredFeed, readAutoUpdate, isMissingManifest, selectFeed, createFeedSelector, isLoopbackFeed, createUpdateController, stateLabel
};
