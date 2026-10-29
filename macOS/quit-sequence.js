
/* could not */
function createQuitHandler({ teardown, quit, log, onError, defer = setImmediate }) {
  if (typeof teardown !== 'function') {
    throw new TypeError('createQuitHandler requires a teardown function');
  }
  if (typeof quit !== 'function') {
    throw new TypeError('createQuitHandler requires a quit function');
  }
  const note = typeof log === 'function' ? log : () => {};
  const report = typeof onError === 'function' ? onError : () => {};

  let phase = 'idle';

  return async function onBeforeQuit(event) {
    if (phase === 'done') {
      return;
    }

    if (event && typeof event.preventDefault === 'function') {
      event.preventDefault();
    }

    if (phase === 'running') {
      note('Quit already in progress; waiting for the server to stop.');
      return;
    }

    phase = 'running';
    note('Quitting: stopping the server before the app goes away...');
    let outcome = null;
    try {
      outcome = await teardown();
    } catch (err) {
      report('Teardown failed during quit; quitting anyway.', err);
    }
    if (outcome && outcome.cancelQuit === true) {
      phase = 'idle';
      note('Quit called off by the teardown; the app stays open.');
      return;
    }
    phase = 'done';
    note('Teardown complete; quitting.');
    defer(quit);
  };
}

module.exports = { createQuitHandler };
