import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const require = createRequire(import.meta.url);
const { rawEnvValue, readEnvValue } = require('../../macOS/env-file.js');

test('rawEnvValue returns the untouched remainder, null when absent', () => {
  assert.equal(rawEnvValue('A=1\nPORT= "8001" \n', 'PORT'), ' "8001" ');
  assert.equal(rawEnvValue('A=1\n', 'PORT'), null);
});

test('rawEnvValue matches only at the start of a line', () => {
  assert.equal(rawEnvValue('XPORT=1\n  PORT=2\n', 'PORT'), null);
});

test('readEnvValue trims whitespace and one quote pair', () => {
  assert.equal(readEnvValue('TOTP_SECRET=" abc "\n', 'TOTP_SECRET'), 'abc');
  assert.equal(readEnvValue('PORT=\n', 'PORT'), '');
  assert.equal(readEnvValue('', 'PORT'), null);
});

test('the first matching line wins', () => {
  assert.equal(readEnvValue('PORT=1\nPORT=2\n', 'PORT'), '1');
});

const { validateEnvFile } = require('../../macOS/env-file.js');

function envDir(text) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'envfile-'));
  if (text !== null) fs.writeFileSync(path.join(dir, '.env'), text);
  return dir;
}
const FULL = 'DEFAULT_WORKING_DIR=/w\nLOG_DIRECTORY=/l\nTOTP_SECRET=t\nJWT_SECRET=j\n';

test('validateEnvFile: a complete file is valid', () => {
  assert.deepEqual(validateEnvFile(envDir(FULL), () => 8000), { isValid: true, missingRequired: [], emptyRequired: [], errors: [] });
});

test('validateEnvFile: absent file, missing field, empty field and a bad port each name themselves', () => {
  assert.match(validateEnvFile(envDir(null), () => 8000).errors[0], /\.env file not found/);
  const missing = validateEnvFile(envDir('LOG_DIRECTORY=/l\nTOTP_SECRET=t\nJWT_SECRET=\n'), () => 8000);
  assert.deepEqual(missing.missingRequired, ['DEFAULT_WORKING_DIR']);
  assert.deepEqual(missing.emptyRequired, ['JWT_SECRET']);
  assert.equal(missing.isValid, false);
  const badPort = validateEnvFile(envDir(FULL), () => { throw new Error('PORT bad'); });
  assert.equal(badPort.isValid, false);
  assert.deepEqual(badPort.errors, ['PORT bad']);
});
