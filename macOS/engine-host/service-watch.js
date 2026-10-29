'use strict';

async function watchForService(manager) {
  if (!manager.awaitingService) return false;
  if (!manager.serviceOwnsEngine()) { manager.awaitingService = false; return false; }
  if (!(await manager.getHealth())) return false;
  manager.awaitingService = false;
  await manager.start();
  return true;
}

module.exports = { watchForService };
