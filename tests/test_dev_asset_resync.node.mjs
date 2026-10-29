
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(here, '..');
const bootstrap = require(path.join(repoRoot, 'macOS', 'bootstrap.js'));

function stage() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cc-dev-resync-'));
  const src = path.join(root, 'checkout');
  const dst = path.join(root, 'serverDir');
  fs.mkdirSync(path.join(src, 'client'), { recursive: true });
  fs.mkdirSync(path.join(src, 'src'), { recursive: true });
  fs.mkdirSync(path.join(dst, 'client'), { recursive: true });

  fs.writeFileSync(path.join(src, 'client', 'index.html'),
                   'NEW BUILD with the merged client in it');
  fs.writeFileSync(path.join(src, 'client', 'brand-new.css'), 'added');
  fs.writeFileSync(path.join(src, 'src', 'main.py'), 'new server');
  fs.writeFileSync(path.join(dst, 'client', 'index.html'), 'OLD BUILD');
  fs.writeFileSync(path.join(dst, 'client', 'orphan.js'), 'removed upstream');

  fs.writeFileSync(path.join(dst, '.env'), 'SECRET=keepme');
  fs.writeFileSync(path.join(dst, 'config.json'), '{"mine":true}');
  return { src, dst };
}

test('a changed file lands in the served copy, not just a new one', () => {
  const { src, dst } = stage();
  const res = bootstrap.syncBundledAssets({
    serverDir: dst,
    bundleResourcesDir: src,
    isPackaged: true,
  });
  assert.equal(res.ok, true, res.details || 'resync reported not ok');

  const served = path.join(dst, 'client', 'index.html');
  assert.equal(
    fs.readFileSync(served, 'utf8'), 'NEW BUILD with the merged client in it',
    'the EDITED file still holds its old contents - this is the defect: a '
    + 'skip-if-exists copy makes a changed file invisible forever'
  );
  assert.equal(
    fs.readFileSync(path.join(dst, 'client', 'brand-new.css'), 'utf8'),
    'added', 'a newly added file did not land'
  );
  assert.equal(
    fs.readFileSync(path.join(dst, 'src', 'main.py'), 'utf8'),
    'new server', 'src/ did not sync'
  );
});

test('an upstream deletion is removed from the served copy', () => {
  const { src, dst } = stage();
  bootstrap.syncBundledAssets({
    serverDir: dst, bundleResourcesDir: src, isPackaged: true,
  });
  assert.equal(
    fs.existsSync(path.join(dst, 'client', 'orphan.js')), false,
    'a file deleted upstream survived in the served copy, so the app would '
    + 'keep serving it'
  );
});

test('user-owned state outside the allowlist is untouched', () => {
  const { src, dst } = stage();
  bootstrap.syncBundledAssets({
    serverDir: dst, bundleResourcesDir: src, isPackaged: true,
  });
  assert.equal(fs.readFileSync(path.join(dst, '.env'), 'utf8'),
               'SECRET=keepme', '.env was clobbered by the resync');
  assert.equal(fs.readFileSync(path.join(dst, 'config.json'), 'utf8'),
               '{"mine":true}', 'config.json was clobbered by the resync');
});
