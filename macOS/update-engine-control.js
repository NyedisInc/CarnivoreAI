'use strict';


function createUpdateEngineControl({
  getServerManager, getHost, engineApi, stopStatsPolling, startStatsPolling, refreshTray, setSystemQuit, setWindowQuitting
}) {
  async function stopForInstall() {
    const serverManager = getServerManager();
    if (!serverManager) return;
    serverManager.beginQuit();
    stopStatsPolling();
    const result = await getHost().stop(serverManager, { getApi: engineApi });
    if (result && result.stopped === false) {
      throw new Error('the server did not stop, so the update was not installed');
    }
    setSystemQuit(true);
  }

  /* after the install */
  async function restartAfterFailedInstall() {
    const serverManager = getServerManager();
    if (!serverManager) return;
    serverManager.cancelQuit();
    setSystemQuit(false);
    setWindowQuitting(false);
    await getHost().start(serverManager);
    startStatsPolling();
    refreshTray();
  }

  return { stopForInstall, restartAfterFailedInstall };
}

module.exports = { createUpdateEngineControl };
