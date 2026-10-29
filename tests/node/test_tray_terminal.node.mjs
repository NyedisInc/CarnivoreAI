
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const macDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'macOS');
const scripts = require(path.join(macDir, 'terminal-scripts.js'));
const termOpen = require(path.join(macDir, 'terminal-open.js'));
const tray = require(path.join(macDir, 'tray-terminal.js'));

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'tray-terminal-test-'));
const LOG = path.join(work, 'argv.log');
const folder = path.join(work, 'project dir $x `y`');
fs.mkdirSync(folder);

function stub(name, body) {
  const file = path.join(work, name);
  fs.writeFileSync(file, '#!/bin/bash\n' + body + '\n', { mode: 0o755 });
  return file;
}
const record = 'printf "%s\\0" "$(basename "$0")" "$@" >> "$LOG"; printf "\\036" >> "$LOG"';
const tmuxStub = stub('tmux', [
  record,
  'cmd=""; for a in "$@"; do case "$a" in has-session|display-message|attach-session) cmd="$a";; esac; done',
  'case "$cmd" in',
  '  has-session) exit "${STUB_HAS:-0}";;',
  '  display-message) case "$*" in *pane_dead*) echo "${STUB_DEAD:-0}";; *) echo "50 200";; esac;;',
  '  attach-session) echo ATTACHED;;',
  'esac',
].join('\n'));
const claudeStub = stub('claude', record + '\necho "CLAUDE_PWD=$PWD"');
const shellStub = stub('fakeshell', record + '\necho "SHELL_PWD=$PWD"');

function run(text, env = {}) {
  fs.writeFileSync(LOG, '');
  const dir = fs.mkdtempSync(path.join(work, 'run-'));
  const file = path.join(dir, 'x.command');
  fs.writeFileSync(file, text, { mode: 0o700 });
  const out = execFileSync('/bin/bash', [file], { env: { PATH: '/usr/bin:/bin', LOG, ...env }, encoding: 'utf8' });
  assert.equal(fs.existsSync(file), false, 'the script deletes itself');
  assert.equal(fs.existsSync(dir), false, 'the script removes its private directory');
  const calls = fs.readFileSync(LOG, 'utf8').split('\x1e').filter(Boolean).map((r) => r.split('\0').slice(0, -1));
  return { out, calls };
}

const spec = (over = {}) => ({
  tmuxBin: tmuxStub, socketPath: '/tmp/tmux-501/cloude', tmuxName: 'carnivore_demo', folder,
  homeFolder: work, shellBin: shellStub, claudeBin: claudeStub, label: 'demo', ...over,
});

{
  const { out, calls } = run(scripts.buildSessionScript(spec()));
  assert.match(out, /Detach with Ctrl-b d/);
  assert.ok(out.includes('\x1b[8;50;200t'), 'the terminal is asked to match the pane size');
  assert.ok(out.includes('ATTACHED'));
  const attach = calls.find((c) => c.includes('attach-session'));
  assert.deepEqual(attach, ['tmux', '-f', '/dev/null', '-S', '/tmp/tmux-501/cloude', 'attach-session', '-t', '=carnivore_demo']);
  assert.ok(calls.every((c) => c[0] === 'tmux'), 'claude does not run when the session is alive');
}

{
  const { out, calls } = run(scripts.buildSessionScript(spec()), { STUB_HAS: '1' });
  assert.match(out, /tmux is not running demo, so this is a plain claude outside Carnivore/);
  assert.ok(out.includes('CLAUDE_PWD=' + folder));
  assert.ok(!calls.some((c) => c.includes('attach-session')));
}

{
  const gone = path.join(work, 'gone dir');
  const { out, calls } = run(scripts.buildSessionScript(spec({ folder: gone })), { STUB_HAS: '1' });
  assert.ok(out.includes('gone dir is gone, so claude was not started'));
  assert.ok(out.includes('SHELL_PWD=' + work), 'plain shell in home');
  assert.deepEqual(calls.map((c) => c[0]), ['tmux', 'fakeshell']);
  assert.ok(!out.includes('CLAUDE_PWD='));
  assert.throws(() => scripts.buildSessionScript(spec({ homeFolder: 'rel' })));
}

{
  const { out, calls } = run(scripts.buildSessionScript(spec()), { STUB_DEAD: '1' });
  assert.ok(out.includes('CLAUDE_PWD=' + folder));
  assert.ok(!calls.some((c) => c.includes('attach-session')));
}

{
  assert.ok(run(scripts.buildSessionScript(spec({ tmuxBin: null }))).out.includes('CLAUDE_PWD=' + folder));
  const { out, calls } = run(scripts.buildSessionScript(spec({ tmuxName: null, label: 'SysOp' })));
  assert.match(out, /SysOp has no live tmux session/);
  assert.deepEqual(calls.map((c) => c[0]), ['claude']);
}

for (const name of ["it's", 'say "hi"', '$HOME', '`id`', 'two words', 'line\nbreak', '-leading', "a'b\"c$d`e f\ng"]) {
  const { calls } = run(scripts.buildSessionScript(spec({ tmuxName: name, label: name })));
  const attach = calls.find((c) => c.includes('attach-session'));
  assert.ok(attach, `attach ran for ${JSON.stringify(name)}`);
  assert.equal(attach[attach.indexOf('-t') + 1], '=' + name);
  for (const c of calls) {
    const target = c[c.indexOf('-t') + 1];
    assert.ok(target === '=' + name || target === '=' + name + ':', `target for ${JSON.stringify(name)}: ${target}`);
  }
}

assert.throws(() => scripts.buildSessionScript(spec({ tmuxName: 'a\0b' })));
assert.throws(() => scripts.buildSessionScript(spec({ folder: 'relative/dir' })));
assert.throws(() => scripts.buildSessionScript(spec({ claudeBin: 'bin/claude' })));
assert.throws(() => scripts.buildShellScript({ folder, shellBin: 'zsh' }));

{
  const generated = [
    scripts.buildSessionScript(spec()), scripts.buildSessionScript(spec({ tmuxName: null })),
    scripts.buildShellScript({ folder, shellBin: '/bin/zsh' }), scripts.buildOfflineTuiScript({ serverDir: folder }),
  ];
  const sources = [scripts.buildSessionScript, scripts.buildShellScript, scripts.buildOfflineTuiScript]
    .map((fn) => fn.toString());
  const hit = (word, text) => new RegExp(`(^|[\\s'"])${word}([\\s'"]|$)`, 'm').test(text);
  for (const word of scripts.FORBIDDEN_TMUX_WORDS) {
    for (const text of generated.concat(sources)) assert.ok(!hit(word, text), `${word} in a script or builder`);
  }
  for (const word of ['new', 'start']) for (const text of generated) assert.ok(!hit(word, text), `${word} in a script`);
  assert.ok(hit('new-session', 'tq new-session -d'));
}

{
  const { out, calls } = run(scripts.buildShellScript({ folder, shellBin: shellStub }));
  assert.ok(out.includes('SHELL_PWD=' + folder));
  assert.deepEqual(calls, [['fakeshell', '-l']]);
  const offline = scripts.buildOfflineTuiScript({ serverDir: '/x/server' });
  assert.match(offline, /exec \.\/venv\/bin\/python3 -m src\.tui --offline/);
  assert.ok(!/python3 -I/.test(offline));
}

{
  const payload = { python: '/P/python/bin/python3', tmux: '/P/bin/tmux' };
  const offline = scripts.buildOfflineTuiScript({ serverDir: '/x/server', payload });
  assert.match(offline, /export CARNIVORE_BUNDLED_TMUX='\/P\/bin\/tmux'/);
  assert.match(offline, /exec '\/P\/python\/bin\/python3' -m src\.tui --offline/);
  assert.ok(!/venv/.test(offline));
  assert.throws(() => scripts.buildOfflineTuiScript({ serverDir: '/x/server', payload: { python: 'python3', tmux: '/P/bin/tmux' } }));
}

{
  const payload = { python: '/P/python/bin/python3', tmux: '/P/bin/tmux' };
  const offline = scripts.buildOfflineTuiScript({ serverDir: '/x/server', payload, pycache: { PYTHONPYCACHEPREFIX: '/C/pycache' } });
  assert.match(offline, /export PYTHONPYCACHEPREFIX='\/C\/pycache'/);
  const off = scripts.buildOfflineTuiScript({ serverDir: '/x/server', payload, pycache: { PYTHONDONTWRITEBYTECODE: '1' } });
  assert.match(off, /export PYTHONDONTWRITEBYTECODE='1'/);
  assert.ok(!/PYTHONPYCACHEPREFIX/.test(scripts.buildOfflineTuiScript({ serverDir: '/x/server', pycache: { PYTHONPYCACHEPREFIX: '/C' } })));
}

{
  const files = new Set(['/P/bin/tmux', '/opt/homebrew/bin/tmux', '/sock']);
  const fakeFs = {
    statSync: (f) => { if (!files.has(f)) throw new Error('ENOENT'); return { uid: 501, mode: 0o100755, isFile: () => true }; },
    existsSync: (f) => files.has(f),
  };
  const versions = { '/P/bin/tmux': '3.7c', '/opt/homebrew/bin/tmux': '3.6a' };
  const mk = (server, speaks = Object.keys(versions)) => ({
    fs: fakeFs, uid: 501, home: '/h', userShell: null, payload: { tmux: '/P/bin/tmux' },
    execFile: (bin, args, opts, cb) => {
      if (args[0] === '-l') return cb(null, 'CARNIVORE_TMUX=/opt/homebrew/bin/tmux\nCARNIVORE_CLAUDE=\n');
      if (args[0] === '-V') return cb(null, `tmux ${versions[bin]}\n`, '');
      if (server === 'none') return cb(new Error('x'), '', 'no server running on /sock');
      if (!speaks.includes(bin)) return cb(new Error('x'), '', 'protocol version mismatch (client 8, server 7)');
      return cb(null, `${server}\n`, '');
    },
  });
  assert.equal((await termOpen.resolveTools(mk('3.6a'))).tmux, '/P/bin/tmux', 'no socket asked: bundled first');
  assert.equal((await termOpen.resolveTools(mk('none'), '/sock')).tmux, '/P/bin/tmux', 'no live server: bundled first');
  assert.equal((await termOpen.resolveTools(mk('3.7c'), '/sock')).tmux, '/P/bin/tmux', 'live 3.7c server: bundled');
  assert.equal((await termOpen.resolveTools(mk('3.6a'), '/sock')).tmux, '/opt/homebrew/bin/tmux', 'live 3.6a server both clients can talk to: Homebrew 3.6a, not 3.7c');
  assert.equal((await termOpen.resolveTools(mk('3.6a', ['/opt/homebrew/bin/tmux']), '/sock')).tmux, '/opt/homebrew/bin/tmux', 'bundled gets a protocol mismatch: Homebrew');
  const noPayload = { ...mk('3.6a'), payload: null };
  assert.equal((await termOpen.resolveTools(noPayload, '/sock')).tmux, '/opt/homebrew/bin/tmux', 'no payload: today\'s order');
  assert.deepEqual((await termOpen.resolveTools(mk('3.6a'), '/sock')).tmuxCandidates, ['/P/bin/tmux', '/opt/homebrew/bin/tmux']);
  const pick = require(path.join(macDir, 'engine', 'tmux-pick.js'));
  assert.equal(pick.versionsMatch('3.6a', '3.6b'), true);
  assert.equal(pick.versionsMatch('3.6a', '3.7c'), false);
  assert.equal(pick.versionsMatch('master', 'master'), true);
  assert.equal(pick.versionsMatch('master', '3.6a'), false);
  assert.equal(await pick.pickTmuxForSocket([], '/sock', mk('3.6a')), null);
  assert.equal(await pick.pickTmuxForSocket(['/P/bin/tmux', '/opt/homebrew/bin/tmux'], '/sock', mk('3.8')), '/P/bin/tmux');
}

assert.equal(scripts.readSocketName(null), 'cloude');
assert.equal(scripts.readSocketName('{"session":{"tmux_socket_name":"carnivore"}}'), 'carnivore');
assert.equal(scripts.readSocketName('{"session":{"tmux_socket_name":"../evil"}}'), 'cloude');
assert.equal(scripts.socketPath('cloude', 501, undefined), '/tmp/tmux-501/cloude');
assert.equal(scripts.socketPath('cloude', 501, '/var/t'), '/var/t/tmux-501/cloude');
assert.equal(scripts.readProjectsRoot, undefined, 'the projects-folder reader is gone');

assert.deepEqual(termOpen.chooseTerminal('com.googlecode.iterm2'), { bundleId: 'com.googlecode.iterm2', usedFallback: false });
assert.deepEqual(termOpen.chooseTerminal('com.barebones.bbedit'), { bundleId: 'com.apple.Terminal', usedFallback: true });
assert.deepEqual(termOpen.chooseTerminal(null), { bundleId: 'com.apple.Terminal', usedFallback: true });
{
  const calls = [];
  const fakeExec = (cmd, args, opts, cb) => {
    calls.push([cmd, args]);
    cb(null, cmd === 'osascript' ? 'com.barebones.bbedit\n' : '');
  };
  const result = await termOpen.openScriptInTerminal('#!/bin/bash\n', 'x.command', { fs, execFile: fakeExec, tmpdir: work });
  assert.equal(result.opened, true);
  assert.equal(result.usedFallback, true);
  const [cmd, args] = calls[1];
  assert.equal(cmd, '/usr/bin/open');
  assert.deepEqual(args.slice(0, 2), ['-b', 'com.apple.Terminal']);
  const st = fs.statSync(args[2]);
  assert.equal(st.mode & 0o777, 0o700);
  assert.equal(fs.statSync(path.dirname(args[2])).mode & 0o777, 0o700);
  assert.ok(path.basename(path.dirname(args[2])).startsWith(termOpen.SCRIPT_DIR_PREFIX));
}

{
  const sweepDir = fs.mkdtempSync(path.join(work, 'sweep-'));
  const old = path.join(sweepDir, termOpen.SCRIPT_DIR_PREFIX + 'old');
  const fresh = path.join(sweepDir, termOpen.SCRIPT_DIR_PREFIX + 'fresh');
  const other = path.join(sweepDir, 'someone-else');
  for (const d of [old, fresh, other]) fs.mkdirSync(d);
  const past = new Date(Date.now() - 2 * termOpen.STALE_SCRIPT_AGE_MS);
  fs.utimesSync(old, past, past);
  fs.utimesSync(other, past, past);
  const removed = termOpen.sweepStaleScripts({ fs, tmpdir: sweepDir, uid: process.getuid(), now: Date.now() });
  assert.equal(removed, 1);
  assert.deepEqual(fs.readdirSync(sweepDir).sort(), [termOpen.SCRIPT_DIR_PREFIX + 'fresh', 'someone-else']);
}

assert.deepEqual(
  termOpen.parseProbeOutput('welcome!\nCARNIVORE_TMUX=/opt/homebrew/bin/tmux\nCARNIVORE_CLAUDE=\n'),
  { tmux: '/opt/homebrew/bin/tmux', claude: null }
);

assert.equal(typeof tray.openRow, 'function');
assert.equal(typeof tray.attachCommandFor, 'function');

{
  const roster = { agents: [{ rank: 'company', tmux_session: 'x' },
    { rank: 'alpha', tmux_session: 'carnivore_sysop_1', repo_dir: '/p/Alpha', display_name: 'SysOp', host_key: 'local' }] };
  let answer = { reachable: true, data: roster };
  const api = { getAuthed: async (p) => { assert.equal(p, '/api/v1/swarm/roster'); return answer; } };
  assert.deepEqual(await tray.refreshSysop(api), { tmuxName: 'carnivore_sysop_1', folder: '/p/Alpha', label: 'SysOp' });
  answer = { reachable: false, data: null };
  assert.equal((await tray.refreshSysop(api)).tmuxName, 'carnivore_sysop_1');
  answer = { reachable: true, data: { agents: [] } };
  assert.equal((await tray.refreshSysop(api)).tmuxName, null);
}

fs.rmSync(work, { recursive: true, force: true });
console.log('test_tray_terminal: ok');
