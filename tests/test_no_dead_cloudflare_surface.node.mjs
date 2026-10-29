
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const setupSrc = readFileSync(join(ROOT, 'setup.sh'), 'utf8');
const mainSrc = ['main.js', 'tray-menu/snapshot.js', 'tray-menu/model/header.js']
  .map((f) => readFileSync(join(ROOT, 'macOS', f), 'utf8')).join('\n');

let passed = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('  ok   ' + name);
  } catch (err) {
    failures.push(name);
    console.log('  FAIL ' + name + ': ' + err.message);
  }
}

function stripShellComments(src) {
  return src.replace(/^\s*#.*$/gm, '');
}

function stripJsComments(src) {
  return src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

test('setup.sh executes nothing that mentions cloudflare', () => {
  const code = stripShellComments(setupSrc);
  const offending = code
    .split('\n')
    .filter((line) => /cloudflare|cloudflared/i.test(line));
  assert.deepEqual(
    offending,
    [],
    'setup.sh still runs Cloudflare code:\n' + offending.join('\n')
  );
});

test('setup.sh does not gate installation on the cloudflared binary', () => {
  const code = stripShellComments(setupSrc);
  assert.ok(
    !/command\s+-v\s+cloudflared/.test(code),
    'the cloudflared presence gate is back; it exits 1 on machines that ' +
      'have no reason to install it'
  );
});

test('setup.sh collects no credential it cannot store', () => {
  const code = stripShellComments(setupSrc);
  for (const name of ['CF_TOKEN', 'CF_ZONE', 'CF_DOMAIN', 'CF_TUNNEL_NAME']) {
    assert.ok(
      !new RegExp('\\b' + name + '\\b').test(code),
      'setup.sh still binds ' + name + ', a value nothing reads back'
    );
  }
});

test('the setup.sh comments explaining the removal are still there', () => {
  assert.match(setupSrc, /Plan v3\.2/);
  assert.match(setupSrc, /CLOUDFLARE_\*/);
});

test('the tray reads no field the health response cannot carry', () => {
  const code = stripJsComments(mainSrc);
  assert.ok(
    !/tunnel_count|tunnelCount/.test(code),
    'the tray still reads tunnel_count, which HealthResponse does not ' +
      'declare and the response_model therefore strips'
  );
  assert.ok(
    !/Tunnels:/.test(code),
    'the tray still renders a Tunnels row for a demolished subsystem'
  );
});

test('the tray row it was replaced with reads a field that exists', () => {
  const code = stripJsComments(mainSrc);
  assert.match(
    code,
    /local_server_count/,
    'the row now shows nothing at all; HealthResponse.local_server_count is ' +
      'the field that replaced tunnel_count and it should be surfaced'
  );
  assert.match(
    code,
    /t\('menubar\.status\.local_servers', \{ count: snap\.server\.localServerCount \}\)/,
    'local_server_count is read but never rendered'
  );
  assert.match(
    code,
    /typeof health\.local_server_count === 'number' \? health\.local_server_count : null/,
    'the row collapses an unanswered server into the number 0'
  );
});

console.log('');
console.log(
  'no-dead-cloudflare-surface: ' + passed + ' passed, ' + failures.length + ' failed'
);
process.exit(failures.length > 0 ? 1 : 0);
