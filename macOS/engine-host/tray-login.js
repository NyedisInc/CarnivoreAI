'use strict';

function trayLogin({ strategy, installer, service, userData }) {
  if (strategy !== 'launchd-agent' || !service) {
    if (!userData) return installer;
    return {
      isEnabled: () => installer.isEnabled(),
      toggle: (...a) => {
        const result = installer.toggle(...a);
        if (!installer.isEnabled()) require('./login-sync').markLoginOff(userData);
        return result;
      },
    };
  }
  return {
    isEnabled: () => service.isEnabled(),
    toggle: () => {
      if (!service.isEnabled()) return service.register();
      const result = service.unregister();
      require('./login-sync').markLoginOff(userData);
      return result;
    },
  };
}

module.exports = { trayLogin };
