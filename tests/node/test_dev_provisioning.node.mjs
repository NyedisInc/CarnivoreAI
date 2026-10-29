import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const dp = require('../../macOS/dev-provisioning.js');
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'devprov-'));

test('findPython prefers the local venv when not packaged', () => {
  const base = tmp();
  fs.mkdirSync(path.join(base, 'venv', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(base, 'venv', 'bin', 'python3'), '');
  assert.equal(dp.findPython({ baseDir: base, isPackaged: false }), path.join(base, 'venv', 'bin', 'python3'));
});

test('copyRecursive copies nested files', () => {
  const a = tmp(); const b = path.join(tmp(), 'out');
  fs.mkdirSync(path.join(a, 'x'));
  fs.writeFileSync(path.join(a, 'x', 'f.txt'), 'hi');
  dp.copyRecursive(a, b);
  assert.equal(fs.readFileSync(path.join(b, 'x', 'f.txt'), 'utf8'), 'hi');
});

test('ensureServerFiles copies the bundle once when packaged and refuses a folder with no src', () => {
  const res = tmp(); const base = path.join(tmp(), 'srv');
  fs.mkdirSync(path.join(res, 'src')); fs.writeFileSync(path.join(res, 'src', 'm.py'), '');
  fs.writeFileSync(path.join(res, 'setup_auth.py'), 'x');
  dp.ensureServerFiles({ baseDir: base, resourcesPath: res, isPackaged: true });
  assert.ok(fs.existsSync(path.join(base, 'src', 'm.py')));
  assert.ok(fs.existsSync(path.join(base, 'setup_auth.py')));
  assert.throws(() => dp.ensureServerFiles({ baseDir: path.join(tmp(), 'empty'), resourcesPath: res, isPackaged: false }), /Server source files not found/);
});

test('ensureVenv uses an existing venv python, and builds one through exec otherwise', async () => {
  const base = tmp();
  fs.mkdirSync(path.join(base, 'venv', 'bin'), { recursive: true });
  fs.writeFileSync(path.join(base, 'venv', 'bin', 'python3'), '');
  assert.equal(await dp.ensureVenv({ baseDir: base, pythonPath: 'p', exec: () => assert.fail('no exec') }), path.join(base, 'venv', 'bin', 'python3'));
  const fresh = tmp(); fs.writeFileSync(path.join(fresh, 'requirements.txt'), '');
  const cmds = [];
  const got = await dp.ensureVenv({ baseDir: fresh, pythonPath: '/py', exec: (c, cb) => { cmds.push(c); cb(null); } });
  assert.equal(got, path.join(fresh, 'venv', 'bin', 'python3'));
  assert.match(cmds[0], /^"\/py" -m venv /);
  assert.match(cmds[1], /pip install -r/);
  await assert.rejects(dp.ensureVenv({ baseDir: tmp(), pythonPath: '/py', exec: (c, cb) => cb(new Error('boom')) }), /boom/);
});
