
const SUPERVISOR_RESTART = 'restart';
const SUPERVISOR_GAVE_UP = 'gave-up';
const SUPERVISOR_NOT_SUPERVISED = 'not-supervised';

const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_DELAYS_MS = [5000, 15000, 45000];
const DEFAULT_HEALTHY_RESET_MS = 60000;

function createSupervisor(options = {}) {
  const maxAttempts = options.maxAttempts || DEFAULT_MAX_ATTEMPTS;
  const delaysMs = options.delaysMs || DEFAULT_DELAYS_MS;
  const healthyResetMs = Number.isFinite(options.healthyResetMs)
    ? options.healthyResetMs
    : DEFAULT_HEALTHY_RESET_MS;
  const now = typeof options.now === 'function' ? options.now : () => Date.now();

  let attempts = 0;
  let gaveUp = false;
  let upSince = null;
  let message = 'The server has not needed an automatic restart.';

  function recordDown(event = {}) {
    upSince = null;

    if (event.expected === true || event.quitting === true) {
      const why = event.quitting
        ? 'The app is quitting.'
        : 'The server was stopped on purpose.';
      message = why;
      return {
        action: SUPERVISOR_NOT_SUPERVISED,
        attempt: attempts,
        maxAttempts,
        delayMs: 0,
        message,
      };
    }

    if (gaveUp || attempts >= maxAttempts) {
      gaveUp = true;
      message =
        `The server has stopped unexpectedly ${maxAttempts} times, so Cloude ` +
        `Code gave up restarting it automatically. Use Start Server once the ` +
        `problem is fixed - the server log will say what went wrong.`;
      return {
        action: SUPERVISOR_GAVE_UP,
        attempt: attempts,
        maxAttempts,
        delayMs: 0,
        message,
      };
    }

    attempts += 1;
    const delayMs = delaysMs[Math.min(attempts - 1, delaysMs.length - 1)];
    message =
      `The server stopped unexpectedly. Restarting it in ` +
      `${Math.round(delayMs / 1000)}s (attempt ${attempts} of ${maxAttempts}).`;
    return {
      action: SUPERVISOR_RESTART,
      attempt: attempts,
      maxAttempts,
      delayMs,
      message,
    };
  }

  function recordUp() {
    upSince = now();
    if (attempts > 0) {
      message =
        `The server was restarted automatically (attempt ${attempts} of ` +
        `${maxAttempts}). It will stop being counted once it has stayed up ` +
        `for ${Math.round(healthyResetMs / 1000)}s.`;
    }
  }

  function noteStillUp() {
    if (upSince === null) {
      upSince = now();
      return false;
    }
    if (attempts === 0 && !gaveUp) return false;
    if (now() - upSince < healthyResetMs) return false;
    attempts = 0;
    gaveUp = false;
    message = 'The server recovered and has been stable since.';
    return true;
  }

  function reset() {
    attempts = 0;
    gaveUp = false;
    upSince = null;
    message = 'The server has not needed an automatic restart.';
  }

  function status() {
    return { attempts, maxAttempts, gaveUp, message };
  }

  return { recordDown, recordUp, noteStillUp, reset, status };
}

module.exports = {
  createSupervisor,
  SUPERVISOR_RESTART,
  SUPERVISOR_GAVE_UP,
  SUPERVISOR_NOT_SUPERVISED,
  DEFAULT_MAX_ATTEMPTS,
  DEFAULT_DELAYS_MS,
  DEFAULT_HEALTHY_RESET_MS,
};
