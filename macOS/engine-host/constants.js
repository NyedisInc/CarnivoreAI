'use strict';

const path = require('path');

const SERVICE_LABEL = 'ai.carnivore.menubar.engine';
const SERVICE_NAME = `${SERVICE_LABEL}.plist`;
const SERVICE_PLIST_SOURCE = path.join(__dirname, SERVICE_NAME);
const SERVICE_ARG = '--engine-service';
const UNREGISTER_ARG = '--unregister-login-service';
const STRATEGIES = Object.freeze(['detached', 'launchd-agent', 'child']);
const DEFAULT_STRATEGY = 'detached';
const CARRIED_BY = 'R2-06';

function loginServiceReady(strategy) {
  return strategy === 'launchd-agent';
}

module.exports = { SERVICE_LABEL, SERVICE_NAME, SERVICE_PLIST_SOURCE, SERVICE_ARG, UNREGISTER_ARG, STRATEGIES, DEFAULT_STRATEGY, CARRIED_BY, loginServiceReady };
