
'use strict';

const localLogin = require('./local-login');
const memberLaunch = require('./member-launch');
const policy = require('./app-window-policy');

function createMember(deps) {
  const getDoorPath = deps.doorPath || (() => {
    const sm = deps.getServerManager();
    return localLogin.doorPath(undefined, undefined, sm ? sm.getBindReport().door_file : null);
  });
  let label = null;
  let labelAsked = false;

  const isJoined = () => {
    const sm = deps.getServerManager();
    return sm ? sm.getBindReport().joined : null;
  };

  localLogin.registerLocalLogin({
    ipcMain: deps.ipcMain,
    isJoined,
    isAppSender: (event) => deps.appWindow.ownsSender(event && event.sender),
    windowOrigin: () => deps.appWindow.origin(),
    originOf: policy.originOf,
    getDoorPath,
  });

  function learnLabel(joined) {
    if (joined !== true) {
      label = null;
      labelAsked = false;
      return;
    }
    if (labelAsked) return;
    labelAsked = true;
    localLogin.doorMainLabel(getDoorPath()).then((name) => {
      label = name;
      if (deps.onChange) deps.onChange();
    });
  }

  return {
    isJoined,
    mainLabel: () => label,
    tokens: () => localLogin.doorLogin(getDoorPath()),
    onHealth() {
      deps.rebindAfterPair.observeHealth({
        ...deps.rebindDeps(),
        serverManager: deps.getServerManager(),
        appWindow: deps.appWindow,
        onJoinedChange: (joined) => {
          learnLabel(joined);
          const installer = deps.getInstaller();
          if (installer) {
            memberLaunch.applyMemberLaunch({
              joined, dir: deps.dataDir(), installer, launchArgs: deps.launchArgs,
            });
          }
        },
      });
    },
  };
}

module.exports = { createMember };
