// WHY THIS FILE EXISTS
// could not reach

'use strict';

const ATTENTION_STATUSES = Object.freeze([
  'question',
  'notice',
  'finished_unread',
  'dead',
]);

const STATUS_UNKNOWN = 'unknown';

const TRAY_STATES = Object.freeze([
  'crashed',
  'attention',
  'unknown',
  'starting',
  'stopped',
  'update',
  'ok',
]);

function countSessionSignals(sessions) {
  const rows = Array.isArray(sessions) ? sessions : [];
  let attention = 0;
  let unknown = 0;

  for (const row of rows) {
    const status = row && row.activity_status;
    if (ATTENTION_STATUSES.includes(status)) attention += 1;
    else if (status === STATUS_UNKNOWN || !status) unknown += 1;
  }

  return { attention, unknown, total: rows.length };
}

/* could not be determined */
function deriveTrayState(input) {
  const serverState = (input && input.serverState) || 'stopped';
  const sessionsReachable =
    input && input.sessionsReachable !== undefined
      ? Boolean(input.sessionsReachable)
      : Array.isArray(input && input.sessions);
  const counts = countSessionSignals(input && input.sessions);
  const updateState = (input && input.updateState) || null;
  const updateReady = updateState === 'ready' || updateState === 'downloading' || updateState === 'available';
  const setupStatus = (input && input.setupStatus) || null;

  const base = {
    attentionCount: counts.attention,
    unknownCount: counts.unknown,
    sessionCount: counts.total,
  };

  if (serverState === 'stopped') {
    if (input && input.lastExitUnexpected) {
      return { ...base, state: 'crashed', reason: 'the server exited on its own' };
    }
    return { ...base, state: 'stopped', reason: 'the server is stopped' };
  }

  if (serverState === 'starting') {
    return { ...base, state: 'starting', reason: 'the server is starting' };
  }

  if (!sessionsReachable && setupStatus !== 'incomplete') {
    return {
      ...base,
      state: 'unknown',
      reason: 'the session list could not be read',
    };
  }

  if (setupStatus === 'incomplete' || setupStatus === 'undetermined') {
    return {
      ...base,
      state: 'attention',
      reason:
        setupStatus === 'incomplete'
          ? 'setup is not finished'
          : 'setup state could not be determined',
    };
  }

  if (counts.attention > 0) {
    const plural = counts.attention === 1 ? 'session needs' : 'sessions need';
    return {
      ...base,
      state: 'attention',
      reason: `${counts.attention} ${plural} attention`,
    };
  }

  if (counts.unknown > 0) {
    const plural = counts.unknown === 1 ? 'session' : 'sessions';
    return {
      ...base,
      state: 'unknown',
      reason: `${counts.unknown} ${plural} reported an unknown status`,
    };
  }

  if (updateReady) {
    return { ...base, state: 'update', reason: 'an update is available' };
  }

  return { ...base, state: 'ok', reason: 'running, nothing needs attention' };
}

function describeSignals(input) {
  const derived = deriveTrayState(input);
  const serverState = (input && input.serverState) || 'stopped';

  let server = serverState === 'starting' && input.serverNote ? input.serverNote : serverState;
  if (derived.state === 'crashed') server = 'crashed';

  let sessions;
  if (serverState !== 'running') {
    sessions = 'cannot determine (server not running)';
  } else if ((derived.state === 'unknown' && derived.sessionCount === 0)
    || (input.setupStatus === 'incomplete' && input.sessionsReachable !== true && !Array.isArray(input.sessions))) {
    sessions = 'cannot determine';
  } else if (derived.attentionCount > 0) {
    sessions = `${derived.attentionCount} of ${derived.sessionCount} need attention`;
  } else if (derived.unknownCount > 0) {
    sessions = `${derived.unknownCount} of ${derived.sessionCount} unknown`;
  } else {
    sessions = `${derived.sessionCount} running, none need attention`;
  }

  const rawUpdate = (input && input.updateState) || null;
  let update;
  if (rawUpdate === 'ready' || rawUpdate === 'downloading' || rawUpdate === 'available') update = 'update available';
  else if (rawUpdate === 'current') update = 'up to date';
  else update = 'cannot determine';

  const rawSetup = (input && input.setupStatus) || null;
  let setup;
  if (rawSetup === 'complete') setup = 'complete';
  else if (rawSetup === 'incomplete') setup = 'not finished';
  else if (rawSetup === 'undetermined') setup = 'cannot determine';
  else setup = 'cannot determine (not polled yet)';

  return { server, sessions, update, setup };
}

function buildTooltip(input) {
  const signals = describeSignals(input);
  return [
    'Carnivore',
    `Server: ${signals.server}`,
    `Sessions: ${signals.sessions}`,
    `Update: ${signals.update}`,
    `Setup: ${signals.setup}`,
  ].join('\n');
}

function describeBind(input) {
  const effective = (input && input.effectiveHost) || null;
  const configured = (input && input.configuredHost) || null;

  if (!effective) {
    return {
      known: false,
      applied: false,
      label: 'Bind: unknown (not measured)',
      detail:
        'The address this server is listening on has not been measured. ' +
        (configured
          ? 'Configuration asks for ' +
            configured +
            ', which is what was requested and not proof of what is ' +
            'reachable.'
          : 'No bind address is configured either.'),
    };
  }

  if (configured && effective !== configured) {
    return {
      known: true,
      applied: false,
      label:
        'Bind: ' + effective + ' in effect - restart to apply ' + configured,
      detail:
        'Listening on ' +
        effective +
        '. Configuration asks for ' +
        configured +
        ', which needs a server restart to apply - the server binds its ' +
        'socket once at startup and cannot move it.',
    };
  }

  return {
    known: true,
    applied: true,
    label: 'Bind: ' + effective + ' (in effect)',
    detail: 'Listening on ' + effective + ', which is what you configured.',
  };
}

module.exports = {
  ATTENTION_STATUSES,
  describeBind,
  TRAY_STATES,
  countSessionSignals,
  deriveTrayState,
  describeSignals,
  buildTooltip,
};
