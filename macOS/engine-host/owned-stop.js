'use strict';
// could not

const { normalizeVersion } = require('../adoption-decision');

function adoptionReplaced(manager, health) {
  if (manager.ownedProcess === true || !manager.adoptedVersion || !health) return false;
  return normalizeVersion(health.version) !== manager.adoptedVersion;
}

async function holdsEngine(manager) {
  if (manager.ownedProcess === true) return true;
  if (manager.getState() !== 'running' || !manager.adoptedVersion) return false;
  if (adoptionReplaced(manager, await manager.getHealth())) return false;
  if (!manager.processPid || typeof manager.findPortHolderPid !== 'function') return true;
  const now = await manager.findPortHolderPid(manager.getPort());
  return !(Number.isInteger(now) && now !== manager.processPid);
}

function ownedStop({ manager, stopEngine }) {
  return async () => {
    if (await holdsEngine(manager)) return stopEngine();
    return { stopped: false, outcome: 'not-ours', error: 'this service did not start or adopt the engine on the port; leaving the port holder alone' };
  };
}

module.exports = { adoptionReplaced, holdsEngine, ownedStop };
