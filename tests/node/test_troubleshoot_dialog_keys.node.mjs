import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const root = path.join(import.meta.dirname, '..', '..');
const source = fs.readFileSync(path.join(root, 'macOS', 'tray-menu', 'actions', 'troubleshoot.js'), 'utf8');
const catalog = fs.readFileSync(path.join(root, 'client', 'js', 'i18n', 'catalog.en.js'), 'utf8');

test('every menubar.dialog key used by troubleshoot.js is in the catalog', () => {
  const used = new Set([...source.matchAll(/'(menubar\.dialog\.[a-z_.]+)'/g)].map((m) => m[1]));
  assert.ok(used.size > 20, 'the file should use many dialog keys');
  for (const key of used) assert.ok(catalog.includes(`'${key}':`), `missing catalog key ${key}`);
});

test('troubleshoot.js no longer carries English dialog titles', () => {
  for (const literal of ['Kill Port Holder', 'Check Health Now', 'Newest Crash Report', 'Stop the server first']) {
    assert.ok(!source.includes(`'${literal}'`), `${literal} should live in the catalog`);
  }
});
