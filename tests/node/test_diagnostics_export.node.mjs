import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import Module from 'node:module';
import { EventEmitter } from 'node:events';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const repo = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(repo, 'macOS');
const require = Module.createRequire(path.join(macDir, 'x.js'));
const crash = require(path.join(macDir, 'crash-reports.js'));
const { buildZip, ZIP_ENTRY_NAMES } = require(path.join(macDir, 'diagnostics', 'zip.js'));
const { createExport } = require(path.join(macDir, 'diagnostics', 'export.js'));

const CANARY = 'CANARY-TOTP-7f3a91c2d4e5';
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'r117-'));
const modeOf = (p) => (fs.statSync(p).mode & 0o777).toString(8);
const keyT = (k, p) => (p ? `${k} ${JSON.stringify(p)}` : k);
const listZip = (zip) => execFileSync('/usr/bin/unzip', ['-Z1', zip], { encoding: 'utf8' }).split('\n').filter(Boolean);

function fakeState() {
  const state = tmp();
  fs.writeFileSync(path.join(state, '.env'), `TOTP_SECRET=${CANARY}\n`);
  fs.writeFileSync(path.join(state, 'carnivore.db'), `SQLite format 3 ${CANARY}`);
  fs.writeFileSync(path.join(state, 'auth.json'), `{"token":"${CANARY}"}`);
  fs.writeFileSync(path.join(state, 'hook-token'), CANARY);
  const dumps = path.join(state, 'crash-dumps');
  fs.mkdirSync(dumps, { mode: 0o700 });
  fs.writeFileSync(path.join(dumps, 'x.dmp'), `MDMP ${CANARY}`);
  return { state, dumps, log: path.join(state, 'crash-events.log') };
}

async function runExport({ text = '{"schema":2,"ok":true}', cancel = false, over = {} } = {}) {
  const s = fakeState();
  const out = path.join(tmp(), 'saved.zip');
  const calls = { save: 0, box: [], err: [], shown: [], reads: 0 };
  const exp = createExport({
    readDiagnostics: async () => { calls.reads++; return { text, error: text ? null : 'no module' }; },
    dialog: {
      showSaveDialog: async (o) => { calls.save++; calls.saveOpts = o; return cancel ? { canceled: true } : { canceled: false, filePath: out }; },
      showMessageBox: async (o) => { calls.box.push(o); return { response: 0 }; },
      showErrorBox: (a, b) => calls.err.push([a, b]),
    },
    shell: { showItemInFolder: (p) => calls.shown.push(p) },
    fs, t: keyT, version: '9.9.9', dumpsDir: s.dumps, crashLog: s.log, home: os.homedir(), downloadsDir: os.tmpdir(), now: () => new Date('2026-10-23T10:00:00Z'),
    ...over,
  });
  await exp.run();
  return { calls, out, s };
}

test('1 zip: passes unzip -t, holds only allow-listed names, refuses .env, .db, auth.json and dumps', () => {
  const dir = tmp(); const zip = path.join(dir, 'a.zip');
  fs.writeFileSync(zip, buildZip([{ name: 'diagnostics.json', data: Buffer.from('{"a":1}') }, { name: 'README.txt', data: Buffer.from('hi'.repeat(500)) }]));
  execFileSync('/usr/bin/unzip', ['-t', zip]);
  assert.deepEqual(listZip(zip), ['diagnostics.json', 'README.txt']);
  for (const bad of ['.env', 'x.db', 'auth.json', 'x.dmp', '../diagnostics.json', 'sub/diagnostics.json']) {
    assert.throws(() => buildZip([{ name: bad, data: Buffer.from('x') }]), /not allowed/, bad);
  }
  assert.deepEqual([...ZIP_ENTRY_NAMES].sort(), ['README.txt', 'crash-dumps.txt', 'crash-events.log', 'diagnostics.json']);
});

test('2 canary: no secret byte or secret file name enters the zip; the dump is listed by name only', async () => {
  const s0 = await runExport();
  const names = listZip(s0.out);
  assert.deepEqual(names.sort(), ['README.txt', 'crash-dumps.txt', 'crash-events.log', 'diagnostics.json']);
  const raw = fs.readFileSync(s0.out);
  assert.ok(!raw.includes(CANARY), 'canary bytes in the raw zip');
  for (const n of names) assert.ok(!execFileSync('/usr/bin/unzip', ['-p', s0.out, n]).includes(CANARY), n);
  for (const bad of ['.env', 'carnivore.db', 'auth.json', 'hook-token', 'x.dmp']) assert.ok(!names.includes(bad), bad);
  const dumps = execFileSync('/usr/bin/unzip', ['-p', s0.out, 'crash-dumps.txt'], { encoding: 'utf8' });
  assert.match(dumps, /x\.dmp/);
  assert.ok(!dumps.includes(os.homedir()) || !os.homedir().startsWith('/Users'), 'home is written as ~');
  assert.equal(execFileSync('/usr/bin/unzip', ['-p', s0.out, 'diagnostics.json'], { encoding: 'utf8' }), '{"schema":2,"ok":true}');
  assert.equal(modeOf(s0.out), '600');
  assert.equal(s0.calls.shown.length, 1, 'Show in Finder button');
  assert.equal(path.basename(s0.calls.saveOpts.defaultPath).match(/^carnivore-diagnostics-\d{8}-\d{6}\.zip$/)?.length, 1);
});

test('2b fail closed: no bundle text means no dialog and no file; a cancelled save writes nothing', async () => {
  const a = await runExport({ text: null });
  assert.equal(a.calls.save, 0); assert.equal(a.calls.err.length, 1); assert.ok(!fs.existsSync(a.out));
  const b = await runExport({ cancel: true });
  assert.equal(b.calls.save, 1); assert.ok(!fs.existsSync(b.out));
  assert.deepEqual(fs.readdirSync(path.dirname(b.out)), [], 'no temp file left behind');
});

test('3 one read, and no egress code in the new modules', async () => {
  const a = await runExport();
  assert.equal(a.calls.reads, 1);
  const files = [path.join(macDir, 'crash-reports.js'), ...fs.readdirSync(path.join(macDir, 'diagnostics')).map((f) => path.join(macDir, 'diagnostics', f))];
  assert.ok(files.length >= 3);
  for (const f of files) {
    const src = fs.readFileSync(f, 'utf8');
    assert.ok(!/require\(\s*['"](node:)?(http|https|net|tls|dgram|axios|electron-updater)['"]\s*\)/.test(src), `${f} requires a network module`);
    assert.ok(!/\bfetch\(|net\.request|XMLHttpRequest|WebSocket/.test(src), `${f} reaches the network`);
  }
});

test('4 crash reporter: upload off, no submit url, dumps folder 0700, sweep keeps the newest N and drops the old', () => {
  const userData = tmp();
  const calls = { start: [], paths: {} };
  const app = { getPath: () => userData, setPath: (k, v) => { calls.paths[k] = v; } };
  crash.start({ app, crashReporter: { start: (o) => calls.start.push(o) }, fs });
  assert.equal(calls.start.length, 1);
  assert.equal(calls.start[0].uploadToServer, false);
  assert.ok(calls.start[0].submitURL === undefined || calls.start[0].submitURL === '');
  assert.equal(calls.paths.crashDumps, path.join(userData, 'crash-dumps'));
  assert.equal(modeOf(calls.paths.crashDumps), '700');
  const dir = calls.paths.crashDumps; const now = Date.now(); const day = 86400000;
  for (let i = 0; i < 14; i++) {
    const f = path.join(dir, `d${i}.dmp`); fs.writeFileSync(f, 'x'); fs.utimesSync(f, new Date(now - i * 1000), new Date(now - i * 1000));
  }
  const old = path.join(dir, 'old.dmp'); fs.writeFileSync(old, 'x'); fs.utimesSync(old, new Date(now - 40 * day), new Date(now - 40 * day));
  crash.sweepDumps(dir, { fs, now });
  const left = fs.readdirSync(dir).sort();
  assert.equal(left.length, 10); assert.ok(!left.includes('old.dmp')); assert.ok(left.includes('d0.dmp') && !left.includes('d13.dmp'));
});

test('5 handlers: one allow-listed line each, no message or token, log 0600 and capped', () => {
  const dir = tmp(); const logPath = path.join(dir, 'logs', 'crash-events.log');
  const app = new EventEmitter(); const proc = new EventEmitter(); const echoed = [];
  crash.wire({ app, process: proc, fs, logPath, now: () => new Date('2026-10-23T10:00:00Z'), echo: (l) => echoed.push(l) });
  app.emit('render-process-gone', {}, { getURL: () => `http://x/?token=${CANARY}` }, { reason: 'crashed', exitCode: 11 });
  app.emit('child-process-gone', {}, { type: 'GPU', reason: 'killed', exitCode: 9, serviceName: `svc ${CANARY} bad name`, name: `${CANARY}/x` });
  const err = Object.assign(new Error(`boom ${CANARY} /Users/x/secret`), { code: 'ECONNRESET' });
  proc.emit('uncaughtException', err);
  const lines = fs.readFileSync(logPath, 'utf8').split('\n').filter(Boolean);
  assert.equal(lines.length, 3); assert.equal(echoed.length, 3);
  for (const l of lines) assert.match(l, crash.CRASH_LINE);
  assert.ok(!lines.join('\n').includes(CANARY));
  assert.ok(!echoed.join('\n').includes(CANARY));
  assert.equal(modeOf(logPath), '600');
  fs.appendFileSync(logPath, `${lines[0]}\n`.repeat(20000));
  crash.capLog(logPath, { fs });
  assert.ok(fs.statSync(logPath).size <= 256 * 1024);
  assert.equal(crash.formatLine('nope', {}), null, 'an unknown event writes nothing');
});

function gate(src) {
  const hits = []; const bad = /token|secret|otp|totp|password/i;
  const re = /\b(?:console\.\w+|logger\.\w+|log)\s*\(/g; let m;
  while ((m = re.exec(src))) {
    let depth = 1; let i = re.lastIndex;
    while (i < src.length && depth) { const c = src[i++]; if (c === '(') depth++; else if (c === ')') depth--; }
    const args = src.slice(re.lastIndex, i - 1);
    const idents = [...args.matchAll(/\$\{([^}]*)\}/g)].map((x) => x[1]);
    const bare = args.replace(/`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"/g, '');
    idents.push(...(bare.match(/[A-Za-z_$][\w$.]*/g) || []));
    if (idents.some((s) => bad.test(s))) hits.push(args.slice(0, 80));
  }
  return hits;
}
function walk(dir, out = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules') continue;
    const p = path.join(dir, e.name);
    if (e.isDirectory()) walk(p, out); else if (e.name.endsWith('.js')) out.push(p);
  }
  return out;
}

test('6 grep gate: no log line in macOS/ names a token, secret, otp, totp or password; the gate can go red', () => {
  assert.equal(gate('console.log(`len ${totpSecretLen}`)').length, 1);
  assert.equal(gate('log("x", authToken)').length, 1);
  assert.equal(gate('console.log("[otp] failed:", err.message)').length, 0);
  const files = walk(macDir);
  assert.ok(files.length > 40, 'the gate looked at a population');
  const found = files.flatMap((f) => gate(fs.readFileSync(f, 'utf8')).map((h) => `${path.relative(repo, f)}: ${h}`));
  assert.deepEqual(found, []);
});

test('7 wiring: Help item enabled and a main action; the tray rows exist in both layouts and register once', async () => {
  const { buildTemplate } = require(path.join(macDir, 'app-menu', 'index.js'));
  const { MAIN_ACTIONS } = require(path.join(macDir, 'app-menu', 'commands.js'));
  let ran = 0;
  const tpl = buildTemplate({ t: (k) => k, appName: 'C', isPackaged: true, appWindow: {}, showAbout() {}, quitAndStopEngine() {}, openUrl() {},
    waiting: () => null, exportDiagnostics: () => { ran++; } });
  const item = tpl.find((m) => m.id === 'help').submenu.find((i) => i.id === 'help.export_diagnostics');
  assert.ok(item.enabled !== false && !item.pending && MAIN_ACTIONS.includes('help.export_diagnostics'));
  item.click(); assert.equal(ran, 1);
  const fx = await import('./tray_menu_fixtures.mjs');
  const { buildMenuModel } = fx.load('model/index.js');
  const up = buildMenuModel(fx.snap(), fx.env); const down = buildMenuModel(fx.snap({ server: { state: 'stopped' } }), fx.env);
  const hasKind = (items) => JSON.stringify(items).includes('"kind":"server.export_diagnostics"');
  assert.ok(hasKind(up) && hasKind(down));
  const { allHandlers } = require(path.join(macDir, 'tray-menu', 'actions', 'index.js'));
  const ctx = { serverManager: { baseDir: '/x', logFile: '/x/l' }, data: {}, dialog: {}, shell: {}, fs, app: { getPath: () => '/x' }, t: (k) => k };
  assert.equal(typeof allHandlers(ctx)['server.export_diagnostics'], 'function');
});

test('8 engine: faulthandler is enabled inside the __main__ block of src/main.py', () => {
  const src = fs.readFileSync(path.join(repo, 'src', 'main.py'), 'utf8');
  const block = src.slice(src.indexOf('if __name__ == "__main__":'));
  assert.match(block, /faulthandler\.enable\(/);
});
