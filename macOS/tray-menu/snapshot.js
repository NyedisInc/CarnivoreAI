
'use strict';

const trayTerminal = require('../tray-terminal');

function gatherSnapshot(d) {
  const sm = d.serverManager;
  const parts = d.data.parts();
  const update = d.autoUpdate.getState();
  const joined = d.member.isJoined() === true;
  const health = d.health || null;
  return {
    now: Date.now(),
    optionKey: Boolean(d.optionKey),
    appVersion: d.appVersion,
    server: {
      state: sm.getState(),
      waitNote: sm.startWait ? sm.startNoteText || null : null,
      version: health && typeof health.version === 'string' ? health.version : null,
      localServerCount: health && typeof health.local_server_count === 'number' ? health.local_server_count : null,
      supervisor: sm.getSupervisorStatus(),
      lastExitUnexpected: Boolean(sm.lastExitUnexpected),
      startBlockedReason: sm.startBlockedReason || null,
      portTrust: parts.portTrust,
      portHolder: parts.portHolder,
    },
    setup: sm.getSetupVerdict().status,
    joined,
    mainLabel: d.member.mainLabel(),
    autoUpdate: d.autoUpdate.isAutoUpdate() === true,
    update: { state: update.state, version: update.version || null, percent: update.percent || 0, detail: update.detail || null },
    listing: parts.listing,
    side: parts.side,
    routes: parts.routes,
    offline: parts.offline,
    phone: {
      bindHost: sm.getBindHost(),
      localIps: sm.getLocalInterfaceIps(),
      effectiveHost: sm.getEffectiveBindHost(),
      measuredUrl: sm.getMeasuredUrl(),
      publishedUrl: sm.getPublishedUrl(),
      otp: joined ? null : sm.getCurrentOtp(),
      otpRemaining: sm.getOtpSecondsRemaining(),
    },
    launchAtLogin: d.launchAgentInstaller.isEnabled(),
    offlineTuiAvailable: sm.getState() === 'stopped' && trayTerminal.offlineTuiAvailable(sm.baseDir, sm.payload),
    sysop: trayTerminal.currentSysop(),
  };
}

function trayStatusInput(snap) {
  return {
    serverState: snap.server.state,
    serverNote: snap.server.waitNote,
    lastExitUnexpected: snap.server.lastExitUnexpected,
    sessions: snap.listing.rows,
    sessionsReachable: snap.listing.reachable,
    updateState: snap.update.state,
    setupStatus: snap.setup,
  };
}

module.exports = { gatherSnapshot, trayStatusInput };
