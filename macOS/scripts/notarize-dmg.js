'use strict';


const { spawnSync } = require('child_process');

const NOTARY_TIMEOUT = '30m';

function xcrun(args) {
  const result = spawnSync('xcrun', args, { encoding: 'utf8' });
  if (result.error) {
    throw result.error;
  }
  return result;
}

function notarizeOne(dmg, api) {
  const auth = ['--key', api.key, '--key-id', api.keyId, '--issuer', api.issuer];
  const submit = xcrun(['notarytool', 'submit', dmg, ...auth, '--wait', '--timeout', NOTARY_TIMEOUT, '--output-format', 'json']);
  let verdict = {};
  try {
    verdict = JSON.parse(submit.stdout);
  } catch (err) {
  }
  if (submit.status !== 0 || verdict.status !== 'Accepted') {
    throw new Error(
      `notarytool submit exited ${submit.status} with status "${verdict.status}" for ${dmg} ` +
        `(submission ${verdict.id}). Read the reason with: xcrun notarytool log ${verdict.id} ` +
        `${auth.join(' ')}. ${(submit.stderr || '').trim()}`
    );
  }
  for (const step of ['staple', 'validate']) {
    const result = xcrun(['stapler', step, dmg]);
    if (result.status !== 0) {
      throw new Error(`stapler ${step} exited ${result.status} for ${dmg}: ${(result.stdout + result.stderr).trim()}`);
    }
  }
  console.log(`[notarize-dmg] notarized and stapled ${dmg} (submission ${verdict.id})`);
}

module.exports = async function notarizeDmgHook(buildResult) {
  if (buildResult.configuration?.mac?.identity == null) {
    console.log('[notarize-dmg] mac.identity is null (an ad hoc build), so the DMG is NOT notarized');
    return [];
  }
  const dmgs = buildResult.artifactPaths.filter((p) => p.endsWith('.dmg'));
  const api = { key: process.env.APPLE_API_KEY, keyId: process.env.APPLE_API_KEY_ID, issuer: process.env.APPLE_API_ISSUER };
  const configured = Boolean(api.key && api.keyId && api.issuer);
  if (dmgs.length > 0 && !configured) {
    console.log('[notarize-dmg] the APPLE_API_* variables are not set, so the DMG is NOT notarized');
  }
  if (configured) {
    for (const dmg of dmgs) {
      notarizeOne(dmg, api);
    }
  }
  return [];
};
