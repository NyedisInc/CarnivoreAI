// WHY THIS FILE EXISTS
// The owner ran the setup script, it succeeded, the app restarted, and the
// watching.

'use strict';

const REQUIRED_ENV_KEYS = Object.freeze(['TOTP_SECRET', 'JWT_SECRET']);

const CHECK_KEYS = Object.freeze([
  'config_file',
  'totp_secret',
  'jwt_secret',
  'totp_paired',
]);

const COMPLETE = 'complete';
const INCOMPLETE = 'incomplete';
const UNDETERMINED = 'undetermined';

function readEnvValue(envText, key) {
  const match = envText.match(new RegExp('^' + key + '=(.*)$', 'm'));
  if (!match) return null;
  const value = match[1].trim().replace(/^"(.*)"$/, '$1').trim();
  return value === '' ? null : value;
}

function evaluateLocalSetup(facts) {
  const envText = (facts && facts.envText) || null;
  const configText =
    facts && facts.configText !== undefined ? facts.configText : null;
  const pairedExists = facts ? facts.pairedExists : null;
  const checks = [];

  if (configText === null || configText === undefined) {
    checks.push({
      key: 'config_file',
      passed: false,
      detail: 'No configuration file yet. Setup writes one when you finish.',
    });
  } else {
    try {
      JSON.parse(configText);
      checks.push({
        key: 'config_file',
        passed: true,
        detail: 'Configuration file present and readable.',
      });
    } catch (err) {
      checks.push({
        key: 'config_file',
        passed: null,
        detail:
          'The configuration file exists but is not valid JSON (' +
          err.message +
          '), so whether this instance is set up cannot be determined.',
      });
    }
  }

  for (const key of REQUIRED_ENV_KEYS) {
    const present = envText !== null && readEnvValue(envText, key) !== null;
    checks.push({
      key: key.toLowerCase(),
      passed: present,
      detail: present
        ? key + ' is configured.'
        : key + ' is not configured, so setup has not finished.',
    });
  }

  checks.push({
    key: 'totp_paired',
    passed: pairedExists === null ? null : Boolean(pairedExists),
    detail:
      pairedExists === null
        ? 'Whether an authenticator has been paired could not be determined.'
        : pairedExists
          ? 'An authenticator has been paired with this instance.'
          : 'No authenticator has been paired yet.',
  });

  let status;
  if (checks.some((c) => c.passed === null)) status = UNDETERMINED;
  else if (checks.every((c) => c.passed === true)) status = COMPLETE;
  else status = INCOMPLETE;

  return { status, checks };
}

function resolveSetupVerdict(input) {
  const serverStatus = (input && input.serverStatus) || null;
  const local = (input && input.local) || { status: UNDETERMINED };

  if (serverStatus) {
    return {
      status: serverStatus,
      source: 'server',
      reason: 'The server reported this directly.',
    };
  }

  return {
    status: local.status,
    source: 'local',
    reason:
      'The server has not answered, so this was read from the files on ' +
      'this machine instead.',
  };
}

module.exports = {
  REQUIRED_ENV_KEYS,
  CHECK_KEYS,
  COMPLETE,
  INCOMPLETE,
  UNDETERMINED,
  readEnvValue,
  evaluateLocalSetup,
  resolveSetupVerdict,
};
