'use strict';

const SHUTDOWN_ROUTE = '/api/v1/shutdown';
const PORT_FREE_BUDGET_MS = 20000;
const PORT_FREE_POLL_MS = 250;

async function stopEngineViaRoute({
  getApi, isUp, verifyHolder = null, setupIncomplete = () => false, signalHolder = null, budgetMs = PORT_FREE_BUDGET_MS, pollMs = PORT_FREE_POLL_MS,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)), now = () => Date.now(), log = () => {},
}) {
  if (!(await isUp())) return { stopped: true, outcome: 'already-down' };
  const refusal = verifyHolder ? await verifyHolder() : null;
  if (refusal) {
    const error = `the listener on the engine port is not provably this user's own (${refusal.reason}); no credential was sent`;
    log(`[engine-stop] ${error}`);
    return { stopped: false, outcome: 'holder-refused', error };
  }
  if (signalHolder && setupIncomplete()) {
    const sent = await signalHolder();
    if (!sent.ok) {
      log(`[engine-stop] unpaired stop failed: ${sent.error}`);
      return { stopped: false, outcome: 'route-failed', error: sent.error || 'the engine could not be signalled' };
    }
  } else {
    const api = getApi();
    if (!api) return { stopped: false, outcome: 'no-api', error: 'no signed-in client for the engine' };

    const answer = await api.sendAuthed(SHUTDOWN_ROUTE, {}, 'POST');
    if (!answer || answer.reachable !== true) {
      const error = (answer && answer.error) || 'the shutdown route did not answer';
      log(`[engine-stop] shutdown route refused: ${error}`);
      return { stopped: false, outcome: 'route-failed', error };
    }
  }

  const deadline = now() + budgetMs;
  for (;;) {
    if (!(await isUp())) return { stopped: true, outcome: 'stopped' };
    if (now() >= deadline) {
      log('[engine-stop] the engine accepted the shutdown and still answers after the budget');
      return { stopped: false, outcome: 'port-still-held', error: 'the engine did not release its port' };
    }
    await sleep(pollMs);
  }
}

module.exports = { SHUTDOWN_ROUTE, PORT_FREE_BUDGET_MS, stopEngineViaRoute };
