/* could not */

const ADOPT_MATCH = 'match';
const ADOPT_MISMATCH = 'mismatch';
/* CANNOT DETERMINE */
const ADOPT_RUNNING_UNKNOWN = 'running-unknown';
/* CANNOT DETERMINE */
const ADOPT_BUNDLE_UNKNOWN = 'bundle-unknown';

function normalizeVersion(value) {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim().replace(/^v/i, '').trim();
  return trimmed === '' ? null : trimmed;
}

function decideAdoption(input) {
  const source = input || {};
  const running = normalizeVersion(source.runningVersion);
  const bundle = normalizeVersion(source.bundleVersion);

  if (running === null) {
    return {
      adopt: false,
      outcome: ADOPT_RUNNING_UNKNOWN,
      runningVersion: null,
      bundleVersion: bundle,
      reason:
        'A Carnivore server is already running on this port, but it did not ' +
        'report which version it is. That is not proof it is out of date, and ' +
        'it is not proof it is current either - it cannot be determined. ' +
        'Adopting it anyway is how this app once spent four hours running an ' +
        'older version\'s server code.',
    };
  }

  if (bundle === null) {
    return {
      adopt: false,
      outcome: ADOPT_BUNDLE_UNKNOWN,
      runningVersion: running,
      bundleVersion: null,
      reason:
        `A Carnivore server reporting version ${running} is already running ` +
        'on this port, but this app could not determine its OWN version, so ' +
        'there is nothing to compare it against. Comparing against an unknown ' +
        'is not a match.',
    };
  }

  if (running === bundle) {
    return {
      adopt: true,
      outcome: ADOPT_MATCH,
      runningVersion: running,
      bundleVersion: bundle,
      reason:
        `The server already on this port reports version ${running}, which is ` +
        'this app\'s own version, so it is this app\'s code. Adopting it ' +
        'rather than starting a second one.',
    };
  }

  return {
    adopt: false,
    outcome: ADOPT_MISMATCH,
    runningVersion: running,
    bundleVersion: bundle,
    reason:
      `The server already running on this port is version ${running}. This ` +
      `app is version ${bundle}. Adopting it would mean running ${running}'s ` +
      `server code under a ${bundle} app, which is not what an upgrade is ` +
      'supposed to do.',
  };
}

module.exports = {
  decideAdoption,
  normalizeVersion,
  ADOPT_MATCH,
  ADOPT_MISMATCH,
  ADOPT_RUNNING_UNKNOWN,
  ADOPT_BUNDLE_UNKNOWN,
};
