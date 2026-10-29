/* nothing at all */

const STOP_ENGINE_ACTION = 'stop-engine';

const GOVERNED_ACTIONS = ['stop', 'restart', STOP_ENGINE_ACTION];

/* this app did not start */
function decideLifecycleAction(input) {
  const source = input || {};
  const action = source.action;
  const owned = source.owned === true;
  const consented = source.takeOwnership === true;

  let stateAfterRefusal = null;
  if (source.serverResponding === true) stateAfterRefusal = 'running';
  else if (source.serverResponding === false) stateAfterRefusal = 'stopped';

  if (!GOVERNED_ACTIONS.includes(action)) {
    return {
      permitted: false,
      reason: `Unrecognised server action ${JSON.stringify(action)}.`,
      offerTakeOwnership: false,
      stateAfterRefusal: null,
    };
  }

  if (action === STOP_ENGINE_ACTION) {
    return {
      permitted: true,
      reason: '',
      offerTakeOwnership: false,
      stateAfterRefusal: null,
      via: owned ? 'signal' : 'route',
    };
  }

  if (owned || consented) {
    return {
      permitted: true,
      reason: '',
      offerTakeOwnership: false,
      stateAfterRefusal: null,
    };
  }

  const verb = action === 'stop' ? 'stop' : 'restart';
  return {
    permitted: false,
    offerTakeOwnership: true,
    stateAfterRefusal,
    reason:
      `Carnivore did not start the server that is running, so it will not ` +
      `${verb} it on its own. It was already running when this app launched ` +
      `and was adopted rather than replaced. Carnivore can take ownership ` +
      `of it - stopping it and starting its own in its place - but that is ` +
      `your call to make, not the app's.`,
  };
}

module.exports = { decideLifecycleAction, GOVERNED_ACTIONS, STOP_ENGINE_ACTION };
