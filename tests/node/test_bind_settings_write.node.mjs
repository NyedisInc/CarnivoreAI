import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { writeConfigBindHost } = require('../../macOS/bind-settings.js');

const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'bind-settings-'));
const config = path.join(dir, 'config.json');
const before = JSON.stringify({ server_prefs: { port: 8000 }, other: 1 }, null, 2);
try {
  fs.writeFileSync(config, before);

  assert.equal(fs.existsSync(config + '.bak'), false, 'no backup before the first write');
  assert.equal(writeConfigBindHost(config, '0.0.0.0'), true);
  assert.equal(fs.existsSync(config + '.bak'), true, 'the backup was written');
  assert.equal(fs.readFileSync(config + '.bak', 'utf8'), before, 'the backup holds the PRE-write bytes');
  const after = JSON.parse(fs.readFileSync(config, 'utf8'));
  assert.deepEqual(after.server_prefs, { port: 8000, bind_host: '0.0.0.0' }, 'the pick is merged, not replacing the block');
  assert.equal(after.other, 1);
  assert.equal(fs.statSync(config).mode & 0o777, 0o600, 'owner-only, as config_writer keeps it');
  assert.equal(fs.statSync(config + '.bak').mode & 0o777, 0o600);
  assert.deepEqual(fs.readdirSync(dir).sort(), ['config.json', 'config.json.bak'], 'no temp file is left behind');

  fs.writeFileSync(config, '{ nope');
  assert.equal(writeConfigBindHost(config, '1.2.3.4'), false);
  assert.equal(fs.readFileSync(config, 'utf8'), '{ nope');
  assert.equal(fs.readFileSync(config + '.bak', 'utf8'), before);

  const missing = path.join(dir, 'gone.json');
  assert.equal(writeConfigBindHost(missing, '1.2.3.4'), false);
  assert.equal(fs.existsSync(missing + '.bak'), false);
} finally {
  fs.rmSync(dir, { recursive: true, force: true });
}
console.log('ALL PASS');
