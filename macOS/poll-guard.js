
'use strict';

async function runGuardedPoll(body, reschedule, log = console.warn) {
  try {
    await body();
  } catch (error) {
    log(`[poll] tick failed: ${(error && error.message) || error}`);
  } finally {
    reschedule();
  }
}

module.exports = { runGuardedPoll };
