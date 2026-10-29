
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const macDir = path.join(here, '..', 'macOS');
const managerSrc = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
const mainPySrc = fs.readFileSync(
  path.join(here, '..', 'src', 'main.py'),
  'utf8'
);

const {
  RotatingLogWriter,
  appendWithRotation,
  rotate,
  DEFAULT_MAX_BYTES,
  DEFAULT_BACKUP_COUNT,
} = require(path.join(macDir, 'log-rotation.js'));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  ok   ${name}`);
    passed += 1;
  } catch (err) {
    console.log(`  FAIL ${name}`);
    console.log(`       ${err.message}`);
    failed += 1;
  }
}

function makeTmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'cloude-log-rotation-'));
}

console.log('log-rotation: server.log must stay bounded, never split, never doubled');


test('the default policy is exactly the ruling: 50 MB, 5 backups', () => {
  assert.equal(DEFAULT_MAX_BYTES, 50 * 1024 * 1024);
  assert.equal(DEFAULT_BACKUP_COUNT, 5);
});


test('a write that would exceed maxBytes rotates the file first', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'server.log');
  const writer = new RotatingLogWriter(target, { maxBytes: 100, backupCount: 5 });
  writer.write('a'.repeat(90));
  assert.ok(!fs.existsSync(`${target}.1`), 'rotated before the file was even close to full');
  writer.write('b'.repeat(90));
  writer.end();
  assert.ok(fs.existsSync(`${target}.1`), 'the file never rotated even though it was pushed past maxBytes');
  assert.equal(fs.readFileSync(`${target}.1`, 'utf8'), 'a'.repeat(90), 'the rotated-out backup does not hold what was in the live file before rotation');
  assert.equal(fs.readFileSync(target, 'utf8'), 'b'.repeat(90), 'the live file after rotation does not hold the chunk that triggered it');
});

test('a file that never reaches maxBytes is never rotated', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'server.log');
  const writer = new RotatingLogWriter(target, { maxBytes: 10_000, backupCount: 5 });
  for (let i = 0; i < 20; i += 1) writer.write(`line ${i}\n`);
  writer.end();
  assert.ok(!fs.existsSync(`${target}.1`), 'rotated a file that never came close to its limit');
});


test('THE CAP IS REAL: backups never exceed backupCount', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'server.log');
  const writer = new RotatingLogWriter(target, { maxBytes: 20, backupCount: 5 });
  for (let i = 0; i < 30; i += 1) {
    writer.write(`chunk-${String(i).padStart(3, '0')}\n`);
  }
  writer.end();
  for (let i = 1; i <= 5; i += 1) {
    assert.ok(fs.existsSync(`${target}.${i}`), `backup .${i} is missing after 30 rotations`);
  }
  assert.ok(
    !fs.existsSync(`${target}.6`),
    'a 6th backup exists - the cap of 5 is not being enforced, which is exactly ' +
    'how server.log grew very large in the first place: an unbounded number of files'
  );
});


test('NO LINE LOST: every written line survives across many rotations, none duplicated', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'server.log');
  const backupCount = 1000;
  const writer = new RotatingLogWriter(target, { maxBytes: 15, backupCount });
  const lines = [];
  for (let i = 0; i < 100; i += 1) {
    const line = `entry-${String(i).padStart(4, '0')}\n`;
    lines.push(line);
    writer.write(line);
  }
  writer.end();

  let rebuilt = '';
  for (let i = backupCount; i >= 1; i -= 1) {
    const p = `${target}.${i}`;
    if (fs.existsSync(p)) rebuilt += fs.readFileSync(p, 'utf8');
  }
  rebuilt += fs.readFileSync(target, 'utf8');

  assert.equal(rebuilt, lines.join(''), 'the reassembled log does not match what was written - a rotation split, dropped or duplicated a line');
});

test('a chunk containing multiple lines is never torn mid-line by a rotation', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'server.log');
  const backupCount = 1000;
  const writer = new RotatingLogWriter(target, { maxBytes: 25, backupCount });
  const chunks = [];
  for (let i = 0; i < 40; i += 1) {
    const chunk = `[STDOUT] message number ${i}\n`;
    chunks.push(chunk);
    writer.write(chunk);
  }
  writer.end();
  let rebuilt = '';
  for (let i = backupCount; i >= 1; i -= 1) {
    const p = `${target}.${i}`;
    if (fs.existsSync(p)) rebuilt += fs.readFileSync(p, 'utf8');
  }
  rebuilt += fs.readFileSync(target, 'utf8');
  assert.equal(rebuilt, chunks.join(''));
  for (let i = 1; i <= backupCount; i += 1) {
    const p = `${target}.${i}`;
    if (!fs.existsSync(p)) continue;
    const text = fs.readFileSync(p, 'utf8');
    assert.ok(text.length === 0 || text.endsWith('\n'), `${p} ends mid-line`);
  }
});


test('appendWithRotation rotates the rarely-written startup-errors.log the same way', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'startup-errors.log');
  const opts = { maxBytes: 50, backupCount: 3 };
  for (let i = 0; i < 10; i += 1) {
    appendWithRotation(target, `[error ${i}] something went wrong\n`, opts);
  }
  assert.ok(fs.existsSync(`${target}.1`), 'appendWithRotation never rotated a file pushed well past maxBytes');
  assert.ok(!fs.existsSync(`${target}.4`), 'appendWithRotation is not honouring backupCount');
});

test('rotate() with backupCount 0 truncates instead of keeping a numbered backup', () => {
  const dir = makeTmpDir();
  const target = path.join(dir, 'server.log');
  fs.writeFileSync(target, 'old content');
  rotate(target, 0);
  assert.ok(!fs.existsSync(target), 'backupCount 0 should drop the file entirely, not keep it');
  assert.ok(!fs.existsSync(`${target}.1`), 'backupCount 0 must not create a .1 backup');
});


test('wiring (SOURCE-LEVEL): server.log is rotated at spawn by the detached spawn, never opened by a bare stream', () => {
  const spawnSrc = fs.readFileSync(path.join(macDir, 'engine', 'detached-spawn.js'), 'utf8');
  assert.ok(/spawnDetachedEngine\(/.test(managerSrc), 'server-manager.js does not start the engine through spawnDetachedEngine');
  assert.ok(
    /require\(['"]\.\.\/log-rotation['"]\)/.test(spawnSrc) && /appendWithRotation\(logFile/.test(spawnSrc),
    'detached-spawn.js does not rotate server.log at spawn, so it has no rotation applied to it before the engine opens it'
  );
  assert.ok(
    spawnSrc.indexOf('appendWithRotation(logFile') < spawnSrc.indexOf('openPrivateAppend(logFile)'),
    'the file is opened for the engine BEFORE it is rotated: the engine would keep writing to the rotated-away file'
  );
  assert.ok(
    !/fs\.createWriteStream\(this\.logFile/.test(managerSrc),
    'server.log is opened with a plain, non-rotating fs.createWriteStream - the exact defect that let it grow very large'
  );
});

test('wiring (SOURCE-LEVEL): the shell opens server.log for the engine in exactly one place, and no pipe writer remains', () => {
  const spawnSrc = fs.readFileSync(path.join(macDir, 'engine', 'detached-spawn.js'), 'utf8');
  assert.equal((spawnSrc.match(/openPrivateAppend\(logFile\)/g) || []).length, 1);
  assert.ok(!/new RotatingLogWriter\(/.test(managerSrc), 'a second writer shares the file with the engine, which can corrupt it across a rotation');
});

test('log files the rotating writers create are 0600, and an old 0644 file is tightened', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'carnivore-log-mode-'));
  try {
    const fresh = path.join(dir, 'server.log');
    const writer = new RotatingLogWriter(fresh, { maxBytes: 16, backupCount: 1 });
    writer.write('0123456789abcdef\n');
    writer.write('rotates now\n');
    writer.end();
    assert.equal(fs.statSync(fresh).mode & 0o777, 0o600);
    assert.equal(fs.statSync(`${fresh}.1`).mode & 0o777, 0o600);

    const old = path.join(dir, 'startup-errors.log');
    fs.writeFileSync(old, 'legacy\n', { mode: 0o644 });
    fs.chmodSync(old, 0o644);
    appendWithRotation(old, 'new line\n');
    assert.equal(fs.statSync(old).mode & 0o777, 0o600);
    assert.equal(fs.readFileSync(old, 'utf8'), 'legacy\nnew line\n');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('wiring (SOURCE-LEVEL): Python never opens server.log itself - it only prints to stdout/stderr', () => {
  assert.ok(
    /PrintLoggerFactory\(\)/.test(mainPySrc),
    'structlog is no longer configured to print to stdout, so this check no ' +
    'longer proves Python has no independent file handle on server.log'
  );
  assert.ok(
    !/FileHandler/.test(mainPySrc),
    'src/main.py now attaches a FileHandler, which would make Python a ' +
    'second writer of a file Electron already rotates - that can corrupt it'
  );
});

console.log(`\nlog-rotation: ${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('ALL PASS');
