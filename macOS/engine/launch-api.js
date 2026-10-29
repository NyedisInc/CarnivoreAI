'use strict';
// does not exist yet

function createLaunchApi({ serverManager, member, TrayApiClient, trayApi }) {
  let own = null;
  return () => {
    const live = trayApi();
    if (live) return live;
    const baseUrl = serverManager ? serverManager.getLocalApiUrl() : null;
    if (!baseUrl) return null;
    if (!own || own.baseUrl !== baseUrl) {
      own = new TrayApiClient({ baseUrl, getOtp: () => serverManager.getCurrentOtp(),
        isJoined: member ? member.isJoined : undefined, localLogin: member ? member.tokens : null });
    }
    return own;
  };
}

module.exports = { createLaunchApi };
