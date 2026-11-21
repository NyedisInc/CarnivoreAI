'use strict';


const { spawnSync } = require('child_process');
const { bundleOf } = require('./proof-marker');

const CODESIGN = '/usr/bin/codesign';
const CODESIGN_TIMEOUT_MS = 3000;
const OVERRIDE_ENV_NAMES = ['CARNIVORE_MOCK_KEYCHAIN', 'CLOUDE_MOCK_KEYCHAIN'];
const TRUE_WORDS = new Set(['1', 'true', 'yes', 'on']);
const FALSE_WORDS = new Set(['0', 'false', 'no', 'off']);

function readOverride(env) {
  for (const name of OVERRIDE_ENV_NAMES) {
    const word = String(env[name] || '').trim().toLowerCase();
    if (TRUE_WORDS.has(word)) return true;
    if (FALSE_WORDS.has(word)) return false;
  }
  return null;
}

function teamStatus(output) {
  const text = String(output || '');
  if (!/^CodeDirectory\b/m.test(text)) return 'unknown';
  const m = text.match(/^TeamIdentifier=(.*)$/m);
  if (m === null) return 'no-team';
  const value = m[1].trim();
  return value === '' || value === 'not set' ? 'no-team' : 'team';
}

function readSignatureReport(bundle, run = spawnSync) {
  const r = run(CODESIGN, ['-dv', bundle], { encoding: 'utf8', timeout: CODESIGN_TIMEOUT_MS });
  if (!r || r.error) return '';
  return String(r.stdout || '') + String(r.stderr || '');
}

function shouldUseMockKeychain({ env = {}, report = '' } = {}) {
  const forced = readOverride(env);
  if (forced !== null) return forced;
  return teamStatus(report) === 'no-team';
}

function applyMockKeychainPolicy(app, { env = process.env, exePath = process.execPath, run = spawnSync } = {}) {
  const forced = readOverride(env);
  let report = '';
  if (forced === null) {
    const bundle = bundleOf(exePath);
    report = bundle === null ? '' : readSignatureReport(bundle, run);
  }
  const use = shouldUseMockKeychain({ env, report });
  if (use) app.commandLine.appendSwitch('use-mock-keychain');
  return use;
}

module.exports = { applyMockKeychainPolicy, shouldUseMockKeychain, teamStatus, readOverride, readSignatureReport, OVERRIDE_ENV_NAMES };
