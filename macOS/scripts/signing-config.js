'use strict';


const { execFileSync } = require('child_process');
const { parseIdentities } = require('./signing-keychain');

const SIGNING_TEAM_ID = 'ARD6KN4BX4';

const PAYLOAD_SIGN_IGNORE = '/Contents/Resources/payload/';

function selectSigning(identities, teamId = SIGNING_TEAM_ID) {
  const suffix = ` (${teamId})`;
  const match = identities.find(
    (i) => i.status === null && i.name.startsWith('Developer ID Application: ') && i.name.endsWith(suffix)
  );
  return match
    ? { mode: 'developer-id', sha1: match.sha1, name: match.name, notarize: true }
    : { mode: 'adhoc', notarize: false };
}

function planFor(identities, teamId = SIGNING_TEAM_ID) {
  const picked = selectSigning(identities, teamId);
  if (picked.mode === 'developer-id') return { mode: 'developer-id', sha1: picked.sha1 };
  const suffix = ` (${teamId})`;
  const present = identities.filter((i) => i.name.endsWith(suffix));
  if (present.length === 0) return { mode: 'adhoc' };
  const detail = present.map((i) => `${i.name}: ${i.status || 'not a Developer ID Application identity'}`).join('; ');
  return { mode: 'invalid', reason: `a ${teamId} identity is present but none is valid (${detail})` };
}

function keychainIdentities(keychain) {
  try {
    const out = execFileSync('security', ['find-identity', '-p', 'codesigning', keychain], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return parseIdentities(out);
  } catch (err) {
    const stderr = (err.stderr || '').toString().trim();
    throw new Error(`security find-identity failed for ${keychain}: ${stderr || err.message}`);
  }
}

module.exports = { selectSigning, planFor, keychainIdentities, SIGNING_TEAM_ID, PAYLOAD_SIGN_IGNORE };

if (require.main === module) {
  const keychain = process.argv[2];
  if (!keychain) {
    process.stderr.write('usage: signing-config.js <keychain path>\n');
    process.exit(2);
  }
  try {
    const plan = planFor(keychainIdentities(keychain));
    if (plan.mode === 'invalid') throw new Error(plan.reason);
    process.stdout.write(`${plan.mode === 'developer-id' ? plan.sha1 : 'adhoc'}\n`);
  } catch (err) {
    process.stderr.write(`signing-config.js: ${err.message}\n`);
    process.exit(3);
  }
}
