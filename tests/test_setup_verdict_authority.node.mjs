// WHY THIS FILE EXISTS

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const macDir = path.join(repoRoot, 'macOS');

const verdict = require(path.join(macDir, 'setup-verdict.js'));

let passed = 0;
const failures = [];
function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('  ok   ' + name);
  } catch (err) {
    failures.push(name);
    console.log('  FAIL ' + name + '\n       ' + err.message);
  }
}

const HIS_INSTALL = {
  envText: [
    'HOST=0.0.0.0',
    'PORT=8000',
    'TOTP_SECRET=JBSWY3DPEHPK3PXP',
    'JWT_SECRET=a-real-looking-signing-secret-value',
  ].join('\n'),
  configText: '{"setup_complete": true, "agents": {}}',
  pairedExists: true,
};

console.log('local evaluation');

test('a finished install with no CLOUDFLARE keys evaluates COMPLETE', () => {
  const result = verdict.evaluateLocalSetup(HIS_INSTALL);
  assert.equal(
    result.status,
    'complete',
    'a fully set-up install was judged not set up: ' + JSON.stringify(result)
  );
});

test('no check anywhere mentions a removed Cloudflare credential', () => {
  const keys = verdict.REQUIRED_ENV_KEYS.join(',');
  assert.ok(
    !/CLOUDFLARE/i.test(keys),
    'setup completeness still depends on credentials for a feature that was ' +
      'removed, which is a condition setup cannot satisfy: ' + keys
  );
});

test('a missing secret is INCOMPLETE, so the test above cannot pass by always saying yes', () => {
  const result = verdict.evaluateLocalSetup({
    ...HIS_INSTALL,
    envText: 'HOST=0.0.0.0\nJWT_SECRET=x-y-z',
  });
  assert.equal(result.status, 'incomplete');
});

test('an unpaired authenticator is INCOMPLETE', () => {
  const result = verdict.evaluateLocalSetup({ ...HIS_INSTALL, pairedExists: false });
  assert.equal(result.status, 'incomplete');
});

test('unreadable config is UNDETERMINED, never incomplete', () => {
  const result = verdict.evaluateLocalSetup({ ...HIS_INSTALL, configText: '{not json' });
  assert.equal(result.status, 'undetermined');
});

test('an absent .env is INCOMPLETE, not a crash', () => {
  const result = verdict.evaluateLocalSetup({ ...HIS_INSTALL, envText: null });
  assert.equal(result.status, 'incomplete');
});

console.log('');
console.log('who wins');

test('the SERVER verdict wins whenever the server has given one', () => {
  const resolved = verdict.resolveSetupVerdict({
    serverStatus: 'complete',
    local: { status: 'incomplete', checks: [] },
  });
  assert.equal(resolved.status, 'complete');
  assert.equal(resolved.source, 'server');
});

test('the server wins in the other direction too', () => {
  const resolved = verdict.resolveSetupVerdict({
    serverStatus: 'incomplete',
    local: { status: 'complete', checks: [] },
  });
  assert.equal(resolved.status, 'incomplete');
  assert.equal(resolved.source, 'server');
});

test('with no server answer the local evaluation is used, and SAYS it is local', () => {
  const resolved = verdict.resolveSetupVerdict({
    serverStatus: null,
    local: { status: 'complete', checks: [] },
  });
  assert.equal(resolved.status, 'complete');
  assert.equal(resolved.source, 'local');
});

test('an undetermined local evaluation stays undetermined', () => {
  const resolved = verdict.resolveSetupVerdict({
    serverStatus: null,
    local: { status: 'undetermined', checks: [] },
  });
  assert.equal(resolved.status, 'undetermined');
});

console.log('');
console.log('the two fact lists cannot drift');

test('the local checks are the SAME facts the server evaluates', () => {
  const pySrc = fs.readFileSync(
    path.join(repoRoot, 'src', 'core', 'setup_state.py'),
    'utf8'
  );
  const serverKeys = new Set(
    [...pySrc.matchAll(/SetupCheck\(\s*key="([a-z_]+)"/g)].map((m) => m[1])
  );
  assert.ok(serverKeys.size >= 4, 'could not read the server fact list');

  const trayKeys = new Set(verdict.CHECK_KEYS);
  const trayMissing = [...serverKeys].filter((k) => !trayKeys.has(k));
  const trayExtra = [...trayKeys].filter((k) => !serverKeys.has(k));

  assert.deepEqual(
    trayMissing,
    [],
    'the server requires facts the tray does not check: ' + trayMissing
  );
  assert.deepEqual(
    trayExtra,
    [],
    'the tray requires facts the server does not, which is a condition ' +
      'setup may not be able to satisfy: ' + trayExtra
  );
});

console.log('');
console.log('the menu row (SOURCE-LEVEL - main.js cannot run outside Electron)');

const mainSrc = fs.readFileSync(path.join(macDir, 'tray-menu', 'model', 'header.js'), 'utf8');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');

test('"Finish Setup..." is offered ONLY on a definite incomplete', () => {
  assert.ok(
    !/if\s*\(!configStatus\.isConfigured\)/.test(mainSrc),
    'the row is still gated on the tray\'s private, unsatisfiable verdict'
  );
  const idx = mainSrc.indexOf("'menubar.setup.finish'");
  assert.notEqual(idx, -1, 'the row is gone entirely; it is still wanted');
  const before = mainSrc.slice(Math.max(0, idx - 400), idx);
  assert.match(
    before,
    /snap\.setup\s*===\s*'incomplete'/,
    'the row is not gated on a definite incomplete, so a server that could ' +
      'not be asked would offer it'
  );
});

test('no CLOUDFLARE credential is required anywhere in the tray any more', () => {
  // existed.
  const code = managerSrc
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');
  assert.ok(
    !/CLOUDFLARE_API_TOKEN|CLOUDFLARE_ZONE_ID|CLOUDFLARE_DOMAIN/.test(code),
    'server-manager.js still requires credentials for a removed feature'
  );
  assert.match(managerSrc, /CLOUDFLARE_API_TOKEN/);
});

console.log('');
console.log('setup-verdict-authority: ' + passed + ' passed, ' + failures.length + ' failed');
process.exit(failures.length > 0 ? 1 : 0);
