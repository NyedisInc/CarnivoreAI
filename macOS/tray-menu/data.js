
'use strict';

const portTrust = require('./port-trust');
const side = require('./side-state');
const offlineTmux = require('./offline-tmux');
const { ListingStore } = require('./listing-store');
const { EventsClient } = require('./events-client');
const pairingHold = require('../tray-pairing-hold');

const SIDE_POLL_MS = 30000;
const LISTING_ROUTE = '/api/v1/sessions/listing';

function createTrayData(deps) {
  const sm = deps.serverManager;
  const timers = deps.timers || { setTimeout, clearTimeout, setInterval, clearInterval };
  let api = null;
  let trust = { trusted: null, reason: 'unknown', holder: null, holderText: null };
  let trustKey = null;
  let sideState = side.emptySide();
  let sideTimer = null;
  let pushed = null;
  let offline = { alive: null, tmuxRunning: null, error: null };
  let portHolderText = null;
  const routes = { standDown: 'unknown', logLevelExpiry: 'unknown', diagnostics: 'unknown', keepAwake: 'unknown' };

  const store = new ListingStore(async () => {
    if (!api) throw new Error('the server port is not trusted');
    const result = await api.getAuthed(LISTING_ROUTE);
    if (!result.reachable) throw new Error(result.error || 'the listing could not be read');
    return result.data;
  }, timers);
  store.onChange(() => deps.onChange());

  const events = new EventsClient({
    store,
    onHello: (topics) => {
      pushed = new Set(topics);
      readSide(Object.keys(side.RESOURCES));
    },
    onTopics: (topics) => {
      const names = side.resourcesForTopics(topics);
      if (names.length) readSide(names);
    },
    onState: (up) => { if (!up) pushed = null; },
    onApprovals: (frame) => { if (deps.onApprovals) deps.onApprovals(frame); },
    getBaseUrl: () => (api ? sm.getLocalApiUrl() : null),
    getToken: async () => (api ? (await api.ensureToken()).token : null),
    forgetToken: () => { if (api) api.forgetToken(); },
    WebSocketImpl: deps.WebSocketImpl,
    timers,
  });

  function ensureApi() {
    const url = sm.getLocalApiUrl();
    if (!url) return;
    if (!api) {
      api = new deps.TrayApiClient({ baseUrl: url, getOtp: () => pairingHold.trayOtp(sm), isJoined: deps.member.isJoined,
        localLogin: deps.member.tokens });
    } else {
      api.setBaseUrl(url);
    }
  }

  async function readSide(names) {
    if (!api || names.length === 0) return;
    try {
      sideState = await side.readSide(api, names, sideState);
      if (names.includes('appUpdate') && deps.onAppUpdate) await deps.onAppUpdate(sideState.appUpdate);
      if (names.includes('desktopPrefs') && deps.onDesktopPrefs) deps.onDesktopPrefs(sideState.desktopPrefs);
      if (sideState.keepAwake.status !== 'unknown') routes.keepAwake = sideState.keepAwake.status;
    } catch (error) {
      console.warn('[tray-menu] side read failed:', error && error.message);
    }
    deps.onChange();
  }

  function refreshSide() {
    return readSide(side.onOpenReads(pushed));
  }

  function pollSide() {
    return readSide(side.pollable(pushed));
  }

  function disconnect() {
    events.stop();
    pushed = null;
    if (sideTimer) timers.clearInterval(sideTimer);
    sideTimer = null;
    api = null;
    sideState = side.emptySide();
    if (deps.onApprovals) deps.onApprovals(null);
  }

  async function verifyPort(health) {
    const port = sm.getPort();
    const pd = deps.portDeps();
    const holders = await portTrust.listeners(port, pd);
    const key = `${port}:${(holders || []).map((h) => h.pid).join(',')}`;
    if (key === trustKey && trust.trusted === true) return;
    const verdict = portTrust.judgePort({ holders, myUid: pd.myUid, health });
    trust = { ...verdict, holderText: verdict.holder ? portTrust.describeHolder(verdict.holder) : null };
    trustKey = key;
    if (verdict.trusted !== true) {
      if (verdict.trusted === false) console.warn('[tray-menu] refusing the server port:', verdict.reason, trust.holderText);
      disconnect();
    }
    portHolderText = verdict.trusted === false ? trust.holderText : null;
  }

  async function readOffline() {
    try {
      offline = await offlineTmux.readAliveCount({ serverDir: sm.baseDir, tmuxBin: await deps.resolveTmux(sm.baseDir), deps: deps.offlineDeps() });
    } catch (error) {
      offline = { alive: null, tmuxRunning: null, error: String(error && error.message) };
    }
    const holders = await portTrust.listeners(sm.getPort(), deps.portDeps());
    portHolderText = holders && holders.length ? portTrust.describeHolder(holders[0]) : null;
  }

  return {
    store,
    api: () => (trust.trusted === true ? api : null),
    refreshSide,
    pollSide,
    pushedTopics: () => pushed,
    markRoute(name, status) {
      routes[name] = status;
      deps.onChange();
    },
    async onHealth(health) {
      try {
        if (sm.getState() === 'running' && health) {
          await verifyPort(health);
          if (trust.trusted !== true) return;
          if (pairingHold.setupPending(sm)) { if (api) disconnect(); return; }
          ensureApi();
          events.start();
          if (!sideTimer) {
            sideTimer = timers.setInterval(() => { pollSide(); }, SIDE_POLL_MS);
            readSide(Object.keys(side.RESOURCES));
          }
        } else {
          disconnect();
          trust = { trusted: null, reason: 'unknown', holder: null, holderText: null };
          trustKey = null;
          if (sm.getState() === 'stopped') await readOffline();
        }
      } finally {
        deps.onChange();
      }
    },
    parts() {
      const rows = store.rows('list');
      const error = store.lastError || (rows === null ? (trust.trusted === false ? 'the server port failed the ownership check' : 'not read yet') : null);
      return {
        listing: { rows, reachable: rows !== null && !store.lastError, live: store.isLive(), error },
        side: sideState,
        routes: { ...routes },
        portTrust: trust,
        portHolder: portHolderText,
        offline,
      };
    },
    stop: disconnect,
  };
}

module.exports = { SIDE_POLL_MS, LISTING_ROUTE, createTrayData };
