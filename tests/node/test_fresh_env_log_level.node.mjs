
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '..', '..');
const bootstrap = require(path.join(repoRoot, 'macOS', 'bootstrap.js'));

test('a freshly generated .env sets LOG_LEVEL=ERROR exactly once', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-fresh-env-'));
  const envOutPath = path.join(dir, '.env');
  bootstrap.generateEnvFile({
    envExamplePath: path.join(repoRoot, '.env.example'),
    envOutPath,
    defaultWorkingDir: path.join(dir, 'projects'),
    logDirectory: path.join(dir, 'logs'),
  });
  const levels = fs.readFileSync(envOutPath, 'utf8').split('\n')
    .filter((line) => line.startsWith('LOG_LEVEL='));
  assert.deepEqual(levels, ['LOG_LEVEL=ERROR']);
});
