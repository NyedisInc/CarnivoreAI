
function isAlive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err.code === 'EPERM';
  }
}

async function waitForExit(pid, budgetMs, pollMs) {
  const deadline = Date.now() + budgetMs;
  while (isAlive(pid)) {
    if (Date.now() >= deadline) return false;
    const remaining = deadline - Date.now();
    await new Promise((resolve) =>
      setTimeout(resolve, Math.min(pollMs, Math.max(remaining, 1)))
    );
  }
  return true;
}

/* CANNOT DETERMINE */
async function terminateProcess(pid, opts = {}) {
  const graceMs = Number.isFinite(opts.graceMs) ? opts.graceMs : 3000;
  const killMs = Number.isFinite(opts.killMs) ? opts.killMs : 2000;
  const pollMs = Number.isFinite(opts.pollMs) ? opts.pollMs : 100;
  const started = Date.now();

  if (!Number.isInteger(pid) || pid <= 0) {
    return {
      terminated: false,
      outcome: 'no-pid',
      escalated: false,
      waitedMs: 0,
    };
  }

  try {
    process.kill(pid, 'SIGTERM');
  } catch (err) {
    if (err.code === 'ESRCH') {
      return {
        terminated: true,
        outcome: 'already-gone',
        escalated: false,
        waitedMs: Date.now() - started,
      };
    }
    if (err.code === 'EPERM') {
      return {
        terminated: false,
        outcome: 'not-permitted',
        escalated: false,
        waitedMs: Date.now() - started,
      };
    }
    throw err;
  }

  if (await waitForExit(pid, graceMs, pollMs)) {
    return {
      terminated: true,
      outcome: 'sigterm',
      escalated: false,
      waitedMs: Date.now() - started,
    };
  }

  try {
    process.kill(pid, 'SIGKILL');
  } catch (err) {
    if (err.code === 'ESRCH') {
      return {
        terminated: true,
        outcome: 'sigterm',
        escalated: false,
        waitedMs: Date.now() - started,
      };
    }
    if (err.code === 'EPERM') {
      return {
        terminated: false,
        outcome: 'not-permitted',
        escalated: true,
        waitedMs: Date.now() - started,
      };
    }
    throw err;
  }

  const gone = await waitForExit(pid, killMs, pollMs);
  return {
    terminated: gone,
    outcome: gone ? 'sigkill' : 'still-running',
    escalated: true,
    waitedMs: Date.now() - started,
  };
}

module.exports = { terminateProcess, isAlive, waitForExit };
