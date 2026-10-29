import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';

const require = createRequire(import.meta.url);
const { ensureVerified } = require('../../macOS/cloudflared-pin.js');

const body = Buffer.from('not the pinned binary');
const pins = { arm64: { url: 'https://example.invalid/x.tgz', archiveSha256: 'a', binarySha256: crypto.createHash('sha256').update(body).digest('hex') } };
const noDownload = async () => { throw new Error('download must not run'); };

function binDirWith(content) {
  const binDir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'r2-cf-')), 'bin');
  if (content !== null) { fs.mkdirSync(binDir); fs.writeFileSync(path.join(binDir, 'cloudflared'), content); }
  return binDir;
}

test('verify-only keeps a copy that does not match the pin and says so', async () => {
  const binDir = binDirWith('some other cloudflared');
  await assert.rejects(ensureVerified({ binDir, arch: 'arm64', pins, download: noDownload, verifyOnly: true }), /kept, not used/);
  assert.equal(fs.readFileSync(path.join(binDir, 'cloudflared'), 'utf8'), 'some other cloudflared');
});

test('verify-only returns a copy that matches the pin, and creates nothing when none exists', async () => {
  const good = binDirWith(body);
  assert.equal(await ensureVerified({ binDir: good, arch: 'arm64', pins, download: noDownload, verifyOnly: true }), path.join(good, 'cloudflared'));
  const none = binDirWith(null);
  await assert.rejects(ensureVerified({ binDir: none, arch: 'arm64', pins, download: noDownload, verifyOnly: true }), /no cloudflared in bin/);
  assert.equal(fs.existsSync(none), false);
});
