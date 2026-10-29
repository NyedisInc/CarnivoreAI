
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawn as realSpawn } from 'node:child_process';
import { EventEmitter } from 'node:events';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const macDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'macOS');
const oit = require(path.join(macDir, 'open-in-terminal.js'));
const confirm = require(path.join(macDir, 'terminal-confirm.js'));
const scripts = require(path.join(macDir, 'terminal-scripts.js'));

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'open-in-terminal-test-'));
const NASTY = 'a b\'c"d$e`f;g\nh=i|j&k(l)';
const TMUX = '/opt/test/bin/tmux';
const attach = (name, ...flags) => [TMUX, '-L', 'cloude', 'attach-session', ...(flags.length ? flags : ['-f', 'ignore-size']), '-t', '=' + name];
const safeFs = { statSync: (p) => ({ uid: 0, mode: 0o755, isFile: () => p === TMUX }) };
const fsDeps = { fs: safeFs, uid: 501 };

assert.equal(oit.validateAttachArgv(attach('carnivore_a'), fsDeps, false).ok, true);
assert.equal(oit.validateAttachArgv(attach(NASTY), fsDeps, false).ok, true, 'a nasty name is still ONE element after =');
assert.equal(oit.validateAttachArgv(attach('carnivore_a', '-r'), fsDeps, true).ok, true);
assert.equal(oit.validateAttachArgv(attach('carnivore_a', '-r'), fsDeps, false).ok, false, 'a read-only argv was not asked for');
const evil = [
  ['/bin/sh', '-L', 'cloude', 'attach-session', '-f', 'ignore-size', '-t', '=x; rm -rf ~'],
  [TMUX, '-L', 'cloude', 'attach-session', '-f', 'ignore-size', '-t', 'x'],
  [TMUX, '-L', 'cloude', 'new-session', '-f', 'ignore-size', '-t', '=x'],
  [TMUX, '-L', '../../etc/x', 'attach-session', '-f', 'ignore-size', '-t', '=x'],
  [TMUX, '-S', '/tmp/x', 'attach-session', '-f', 'ignore-size', '-t', '=x'],
  [...attach('x'), '; rm -rf ~'],
  'tmux attach',
  null,
  ['tmux', '-L', 'cloude', 'attach-session', '-f', 'ignore-size', '-t', '=x'],
];
for (const argv of evil) assert.equal(oit.validateAttachArgv(argv, fsDeps, false).ok, false, JSON.stringify(argv));
const unsafeFs = { statSync: () => ({ uid: 501, mode: 0o777, isFile: () => true }) };
assert.equal(oit.validateAttachArgv(attach('x'), { fs: unsafeFs, uid: 501 }, false).ok, false, 'a world-writable tmux is refused');

{
  const log = path.join(work, 'argv.log');
  const stubTmux = path.join(work, 'tmux');
  fs.writeFileSync(stubTmux, '#!/bin/bash\nprintf "%s\\0" "$@" > "$LOG"\n', { mode: 0o755 });
  const argv = [stubTmux, '-L', 'cloude', 'attach-session', '-f', 'ignore-size', '-t', '=' + NASTY];
  const script = scripts.buildAttachScript({ argv, label: 'ses_x', tmuxTmpdir: null });
  const file = path.join(work, 'attach.command');
  fs.writeFileSync(file, script, { mode: 0o755 });
  execFileSync(file, [], { env: { PATH: '/usr/bin:/bin', LOG: log, TMUX_TMPDIR: '/should/be/unset' }, stdio: 'ignore' });
  assert.deepEqual(fs.readFileSync(log, 'utf8').split('\0').slice(0, -1), argv.slice(1));
  assert.equal(fs.existsSync(file), false, 'the script deletes itself');
  assert.throws(() => scripts.buildAttachScript({ argv: ['tmux', 'x'], label: 'x' }), /not usable/);
  assert.ok(/^export TMUX_TMPDIR='\/private\/tmp'$/m.test(scripts.buildAttachScript({ argv, label: 'x', tmuxTmpdir: '/private/tmp' })));
}

assert.deepEqual(oit.splitTemplate('open -na "My Term" --args').words, ['open', '-na', 'My Term', '--args']);
assert.equal(oit.splitTemplate('open "unclosed').ok, false);
assert.equal(oit.splitTemplate('   ').ok, false);
assert.equal(oit.splitTemplate('open -a X\nrm -rf ~').ok, false, 'a newline in the template is refused');
{
  const launch = oit.customLaunch('open -na Ghostty --args -e', attach('carnivore_a'));
  assert.equal(launch.file, '/usr/bin/open');
  assert.deepEqual(launch.args, ['-na', 'Ghostty', '--args', '-e', ...attach('carnivore_a')]);
  assert.equal(oit.customLaunch('osascript -e x', attach('a')).ok, false, 'a bare program name is not searched on PATH');
  assert.equal(oit.customLaunch('/Applications/K.app/Contents/MacOS/kitty', attach('a')).file, '/Applications/K.app/Contents/MacOS/kitty');
}

{
  const dir = fs.mkdtempSync(path.join(work, 'userdata-'));
  const asked = [];
  let click = 0;
  const dialog = { showMessageBox: async (opts) => { asked.push(opts); return { response: click }; } };
  const t = (key) => key;
  const spec = (parts) => ({ argv: [...parts, '=a'], hashParts: parts, dir, dialog, t });
  click = 1;
  assert.equal(await confirm.confirmCustom(spec(['/usr/bin/open', '-na', 'X'])), false);
  assert.equal(fs.existsSync(path.join(dir, confirm.CONFIRMED_FILE)), false, 'a cancel stores nothing');
  click = 0;
  assert.equal(await confirm.confirmCustom(spec(['/usr/bin/open', '-na', 'X'])), true);
  assert.equal(asked.length, 2);
  assert.ok(asked[1].detail.includes('"/usr/bin/open"\n"-na"\n"X"\n"=a"'), 'the exact argv, one JSON-quoted element per line');
  assert.equal(asked[1].defaultId, 1, 'Cancel is the default button');
  assert.equal(fs.statSync(path.join(dir, confirm.CONFIRMED_FILE)).mode & 0o777, 0o600);
  assert.equal(await confirm.confirmCustom(spec(['/usr/bin/open', '-na', 'X'])), true);
  assert.equal(asked.length, 2, 'the same command asks no second time');
  click = 1;
  assert.equal(await confirm.confirmCustom(spec(['/usr/bin/open', '-na', 'Y'])), false);
  assert.equal(asked.length, 3, 'a changed command asks again');
  assert.equal(await confirm.confirmCustom(spec(['/usr/bin/open', '-na', 'X'])), true, 'the cancel kept the earlier approval');
  assert.notEqual(confirm.confirmationHash(['a b']), confirm.confirmationHash(['a', 'b']), 'element boundaries are part of the hash');
}

{
  const calls = [];
  const live = () => ({
    fs: { ...safeFs, mkdtempSync: (p) => fs.mkdtempSync(p), chmodSync: fs.chmodSync, writeFileSync: fs.writeFileSync, rmSync: fs.rmSync,
      readFileSync: fs.readFileSync, renameSync: fs.renameSync },
    tmpdir: work, uid: 501, execFile: (file, args, ...rest) => { calls.push({ file, args }); rest[rest.length - 1](null); },
    spawn: (file, args, options) => {
      calls.push({ file, args, options });
      const child = new EventEmitter(); child.unref = () => {}; setImmediate(() => child.emit('exit', 0, null));
      return child;
    },
  });
  let prefs = { desktop_terminal_app: 'ghostty', desktop_terminal_custom: '' };
  let route = { reachable: true, data: { argv: attach('carnivore_a') } };
  const routes = [];
  const api = { getAuthed: async (r) => { routes.push(r); return r.includes('/preferences') ? { reachable: true, data: { values: prefs } } : route; } };
  const lastAttachRoute = () => routes.filter((r) => r.includes('attach-command')).at(-1);
  const dataDir = fs.mkdtempSync(path.join(work, 'data-'));
  let ran = 0;
  const dialog = { showMessageBox: async () => { ran += 1; return { response: 0 }; } };
  const opener = oit.createOpenInTerminal({ api: () => api, dialog, dataDir: () => dataDir, loadTranslator: async () => (k) => k, live });

  let out = await opener.open('ses_abc');
  assert.deepEqual(out, { opened: true, error: null, reason: 'ok' });
  assert.equal(lastAttachRoute(), '/api/v1/sessions/ses_abc/attach-command');
  assert.equal(calls[0].file, '/usr/bin/open');
  assert.deepEqual(calls[0].args.slice(0, 2), ['-b', 'com.mitchellh.ghostty']);
  assert.ok(calls[0].args[2].endsWith('carnivore-attach.command'));

  out = await opener.open('adopted:some name');
  assert.equal(lastAttachRoute(), '/api/v1/sessions/adopted%3Asome%20name/attach-command');
  await opener.open('ses_abc', { readOnly: true });
  assert.equal(lastAttachRoute(), '/api/v1/sessions/ses_abc/attach-command?read_only=true');

  assert.equal((await opener.open('remote:peer-x:name')).reason, 'remote');
  assert.equal((await opener.open('ses_abc; rm -rf ~')).reason, 'failed');
  route = { reachable: false, status: 409, data: null, error: 'HTTP 409' };
  assert.equal((await opener.open('ses_abc')).reason, 'not_running');
  route = { reachable: true, data: { argv: ['/bin/sh', '-c', 'x'] } };
  assert.equal((await opener.open('ses_abc')).reason, 'failed', 'a server-supplied command that is not the attach shape never runs');

  route = { reachable: true, data: { argv: attach('carnivore_a') } };
  prefs = { desktop_terminal_app: 'custom', desktop_terminal_custom: 'open -na MyTerm --args' };
  calls.length = 0;
  out = await opener.open('ses_abc');
  assert.equal(out.reason, 'ok');
  assert.equal(ran, 1, 'the first custom use showed the dialog');
  assert.deepEqual(calls[0], { file: '/usr/bin/open', args: ['-na', 'MyTerm', '--args', ...attach('carnivore_a')], options: { detached: true, stdio: 'ignore' } });
  await opener.open('ses_abc');
  assert.equal(ran, 1, 'the second use shows no dialog');
  assert.deepEqual((await opener.attachArgv('ses_abc')).argv, attach('carnivore_a'));
  assert.ok(calls.every((c) => c.file !== '/bin/sh' && !c.args.includes('-c')), 'nothing ran through sh -c');
}

{
  const flood = `process.stdout.write('x'.repeat(2*1024*1024)); process.stderr.write('y'.repeat(2*1024*1024)); setTimeout(()=>{}, 300);`;
  const t0 = Date.now();
  const okRun = await oit.runCustom(process.execPath, ['-e', flood], { spawn: realSpawn });
  assert.deepEqual(okRun, { opened: true, error: null }, 'a 4 MB log writer is not killed by a buffer limit (execFile died at 1 MB)');
  assert.ok(Date.now() - t0 >= 250, 'it was judged by the settle, not by an early exit');
  const bad = await oit.runCustom(process.execPath, ['-e', 'process.exit(3)'], { spawn: realSpawn });
  assert.equal(bad.opened, false); assert.match(bad.error, /exited with 3/);
  const missing = await oit.runCustom('/nonexistent/program', [], { spawn: realSpawn });
  assert.equal(missing.opened, false);
}

{
  const sessions = require(path.join(macDir, 'tray-menu', 'actions', 'sessions.js'));
  const trayTerminal = require(path.join(macDir, 'tray-terminal.js'));
  const shown = [];
  const copied = [];
  const makeCtx = (open, argv) => ({ dialog: { showErrorBox: (...a) => shown.push(a), showMessageBox: () => {} }, clipboard: { writeText: (x) => copied.push(x) },
    serverManager: { baseDir: work }, openInTerminal: { open, attachArgv: async () => ({ argv }) } });
  const seen = [];
  const oldOpenRow = trayTerminal.openRow;
  let oldPath = 0;
  trayTerminal.openRow = async () => { oldPath += 1; return { opened: true, usedFallback: false, error: null }; };
  try {
    const action = { kind: 'session.terminal', mode: 'watch', tmuxName: 'carnivore_a', sessionId: 'ses_1', folder: '/w', label: 'one' };
    await sessions.openSessionTerminal(makeCtx(async (id, o) => { seen.push([id, o]); return { opened: true, reason: 'ok' }; }), action);
    assert.deepEqual(seen, [['ses_1', { readOnly: true }]]);
    assert.equal(oldPath, 0);
    await sessions.openSessionTerminal(makeCtx(async () => ({ opened: false, reason: 'cancelled' })), action);
    assert.equal(oldPath, 0, 'a cancelled confirm runs nothing else');
    await sessions.openSessionTerminal(makeCtx(async () => ({ opened: false, reason: 'not_running' })), { ...action, mode: 'type' });
    assert.equal(oldPath, 1, 'an asleep session keeps the old path');
    await sessions.openSessionTerminal(makeCtx(async () => ({ opened: false, reason: 'failed', error: 'boom' })), action);
    assert.equal(oldPath, 1, 'a failure never opens a different terminal');
    assert.equal(shown.length, 1);
    await sessions.copyAttach(makeCtx(null, [TMUX, '-L', 'cloude', 'attach-session', '-t', "=it's a name"]), action);
    assert.deepEqual(copied, [`'${TMUX}' '-L' 'cloude' 'attach-session' '-t' '=it'\\''s a name'`]);
  } finally {
    trayTerminal.openRow = oldOpenRow;
  }
}

fs.rmSync(work, { recursive: true, force: true });
console.log('test_open_in_terminal: ok');
