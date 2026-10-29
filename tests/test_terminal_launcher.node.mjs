// WHY THIS FILE EXISTS
// could not be determined

import assert from 'node:assert/strict';
import fsReal from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFile as execFileReal } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..');
const launcher = require(path.join(repoRoot, 'macOS', 'terminal-launcher.js'));

let passed = 0;
let skipped = 0;
const failures = [];

function test(name, fn) {
  try {
    fn();
    passed += 1;
    console.log('  ok   ' + name);
  } catch (error) {
    failures.push({ name, error });
    console.log('  FAIL ' + name + ': ' + error.message);
  }
}

function openAndWait(logPath, scriptPath, deps) {
  return new Promise((resolve) => {
    launcher.openServerLogInDefaultTerminal(logPath, scriptPath, resolve, deps);
  });
}

function makeDeps(options) {
  const opts = options || {};
  const calls = { writes: [], chmods: [], execFile: [], openPath: [] };

  const deps = {
    fs: {
      writeFileSync(target, contents, fileOptions) {
        calls.writes.push({ target, contents, fileOptions });
        if (opts.writeThrows) throw opts.writeThrows;
      },
      chmodSync(target, mode) {
        calls.chmods.push({ target, mode });
      },
    },
    shell: {
      openPath(target) {
        calls.openPath.push(target);
        return Promise.resolve(
          opts.openPathResult === undefined ? '' : opts.openPathResult
        );
      },
    },
    execFile(bin, args, callback) {
      calls.execFile.push({ bin, args });
      const isDetect = args[0] === '-l';
      if (isDetect) {
        if (opts.handlerError) return callback(opts.handlerError, '');
        return callback(null, opts.handler === null ? '' : opts.handler + '\n');
      }
      return callback(null, '');
    },
  };

  return { deps, calls };
}

const LOG = '/Users/someone/Library/Application Support/cloude-code-menubar/logs/server.log';
const SCRIPT = '/Users/someone/Library/Application Support/cloude-code-menubar/logs/open-server-log.command';

console.log('terminal-launcher: pure builders');

test('the module no longer builds AppleScript (P7: Terminal opens through open -b)', () => {
  assert.equal(launcher.buildTerminalAppleScript, undefined);
  assert.equal(launcher.escapeAppleScriptString, undefined);
});

test('the .command script single quotes the path and execs tail -f', () => {
  const script = launcher.buildTailCommandScript(LOG);
  assert.ok(script.startsWith('#!/bin/bash\n'), 'missing shebang');
  assert.ok(
    script.includes("exec tail -f '" + LOG + "'"),
    'path is not single quoted in the exec line:\n' + script
  );
  assert.ok(script.endsWith('\n'), 'script must end with a newline');
});

test('single quoting makes a backtick inert rather than command substitution', () => {
  const quoted = launcher.shellSingleQuote('/tmp/`whoami`/x.log');
  assert.equal(quoted, "'/tmp/`whoami`/x.log'");
  assert.ok(!quoted.startsWith('"'), 'must not be double quoted');
});

test('single quoting closes and reopens around an embedded single quote', () => {
  assert.equal(launcher.shellSingleQuote("it's"), "'it'\\''s'");
});

console.log('terminal-launcher: default-handler route');

{
  const { deps, calls } = makeDeps({ handler: '/Applications/iTerm.app' });
  const result = await openAndWait(LOG, SCRIPT, deps);
  test('a resolved handler opens the .command via shell.openPath', () => {
  assert.deepEqual(calls.openPath, [SCRIPT], 'shell.openPath not called with the script');
  assert.equal(result.opened, true);
  assert.equal(result.usedFallback, false, 'must not fall back when a handler exists');
  assert.equal(result.handlerPath, '/Applications/iTerm.app');
  const openRuns = calls.execFile.filter((c) => c.bin === '/usr/bin/open');
  assert.equal(openRuns.length, 0, 'Terminal.app must not be opened when a handler resolved');
  });
}

test('the .command file is written executable (mode 0755)', () => {
  const { deps, calls } = makeDeps({ handler: '/Applications/Warp.app' });
  launcher.openServerLogInDefaultTerminal(LOG, SCRIPT, () => {}, deps);

  assert.equal(calls.writes.length, 1);
  assert.equal(calls.writes[0].target, SCRIPT);
  assert.equal(calls.writes[0].fileOptions.mode, 0o755, 'file written non-executable');
  assert.deepEqual(calls.chmods, [{ target: SCRIPT, mode: 0o755 }], 'chmod not re-asserted');
});

test('repeated opens reuse ONE stable path and do not accumulate files', () => {
  const { deps, calls } = makeDeps({ handler: '/Applications/Ghostty.app' });
  launcher.openServerLogInDefaultTerminal(LOG, SCRIPT, () => {}, deps);
  launcher.openServerLogInDefaultTerminal(LOG, SCRIPT, () => {}, deps);

  const targets = new Set(calls.writes.map((w) => w.target));
  assert.equal(calls.writes.length, 2, 'expected two writes');
  assert.equal(targets.size, 1, 'each click wrote a DIFFERENT file: ' + [...targets].join(', '));
});

console.log('terminal-launcher: three outcomes');

{
  const { deps, calls } = makeDeps({ handler: null });
  const result = await openAndWait(LOG, SCRIPT, deps);
  test('COULD NOT DETERMINE a handler falls back AND reports usedFallback', () => {
  assert.equal(result.opened, true, 'fallback should still open something');
  assert.equal(
    result.usedFallback,
    true,
    'an undetermined handler must be reported, not silently substituted'
  );
  assert.equal(result.handlerPath, null);
  assert.deepEqual(calls.openPath, [], 'must not openPath when no handler resolved');

  const opened = calls.execFile.find((c) => c.bin === '/usr/bin/open');
  assert.ok(opened, 'fallback did not open Terminal.app');
  assert.deepEqual(
    opened.args,
    ['-b', 'com.apple.Terminal', SCRIPT],
    'the FALLBACK must open the same script in Terminal.app with open -b (which raises it)'
  );
  assert.equal(calls.execFile.some((c) => c.args[0] === '-e'), false, 'no AppleScript may run');
  });
}

{
  const { deps, calls } = makeDeps({
    handler: '/Applications/iTerm.app',
    openPathResult: 'LSOpenURLsWithRole() failed',
  });
  const result = await openAndWait(LOG, SCRIPT, deps);
  test('a failed shell.openPath falls back rather than reporting success', () => {
    assert.equal(result.usedFallback, true);
    assert.ok(calls.execFile.some((c) => c.bin === '/usr/bin/open'), 'no fallback attempted');
  });
}

{
  const { deps, calls } = makeDeps({
    handler: '/Applications/iTerm.app',
    writeThrows: new Error('EROFS: read-only file system'),
  });
  const result = await openAndWait(LOG, SCRIPT, deps);
  test('an unwritable .command file falls back instead of throwing', () => {
  assert.equal(result.usedFallback, true);
  assert.deepEqual(calls.openPath, []);
  assert.ok(calls.execFile.some((c) => c.bin === '/usr/bin/open'), 'no fallback attempted');
  });
}

{
  const { deps } = makeDeps({ handlerError: new Error('osascript exploded') });
  const result = await openAndWait(LOG, SCRIPT, deps);
  test('a failing handler probe is treated as undetermined, not as success', () => {
    assert.equal(result.handlerPath, null);
    assert.equal(result.usedFallback, true);
  });
}

console.log('terminal-launcher: live LaunchServices probe');

if (os.platform() !== 'darwin') {
  skipped += 1;
  console.log('  skip live handler probe: not darwin (reported as SKIPPED, never as passed)');
} else if (process.env.CARNIVORE_LIVE_LAUNCHSERVICES !== '1') {
  skipped += 1;
  console.log('  skip live handler probe: set CARNIVORE_LIVE_LAUNCHSERVICES=1 to run the real osascript (reported as SKIPPED, never as passed)');
} else {
  const tmpDir = fsReal.mkdtempSync(path.join(os.tmpdir(), 'cloude-cmd-'));
  const probe = path.join(tmpDir, 'probe.command');
  fsReal.writeFileSync(probe, '#!/bin/bash\nexit 0\n', { mode: 0o755 });

  await new Promise((resolve) => {
    launcher.detectDefaultCommandHandler(
      probe,
      (handlerPath) => {
        test('LaunchServices resolves a real handler for a real .command file', () => {
          assert.ok(
            handlerPath && handlerPath.endsWith('.app'),
            'no application bundle resolved for a .command file; got: ' +
              String(handlerPath)
          );
        });
        resolve();
      },
      { execFile: execFileReal }
    );
  });

  fsReal.rmSync(tmpDir, { recursive: true, force: true });
}

console.log('');
console.log(
  'terminal-launcher: ' + passed + ' passed, ' + failures.length +
    ' failed, ' + skipped + ' skipped'
);
process.exit(failures.length > 0 ? 1 : 0);
