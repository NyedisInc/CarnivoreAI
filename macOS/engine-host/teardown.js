'use strict';

function installTermHandler({ proc, role, quit, stopEngine, exit, onSignal = () => {}, log = () => {} }) {
  let fired = false;
  const handler = async () => {
    if (fired) return;
    fired = true;
    if (role !== 'service') {
      log('[teardown] SIGTERM: quitting through the normal quit sequence');
      onSignal();
      quit();
      return;
    }
    try {
      const result = await stopEngine();
      if (result && result.stopped === false) log(`[teardown] the engine was not stopped (${result.outcome}): ${result.error || 'no detail'}`);
    } catch (err) {
      log(`[teardown] the engine stop failed: ${err.message}`);
    }
    exit(0);
  };
  proc.on('SIGTERM', handler);
  return handler;
}

module.exports = { installTermHandler };
