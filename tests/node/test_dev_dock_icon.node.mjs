import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { macDir } from './tray_menu_fixtures.mjs';

const require = createRequire(import.meta.url);
const { applyDevDockIcon } = require(path.join(macDir, 'dev-dock-icon.js'));

function run(over = {}) {
  const set = [];
  const paths = [];
  const app = { isPackaged: !!over.packaged, dock: { setIcon: (i) => set.push(i) } };
  const nativeImage = { createFromPath: (p) => { paths.push(p); return { isEmpty: () => !!over.empty }; } };
  const warns = [];
  const result = applyDevDockIcon({ app, nativeImage, platform: over.platform || 'darwin', log: { warn: (...a) => warns.push(a) } });
  return { set, paths, warns, result };
}

test('dev run on darwin sets the icon from a file that exists', () => {
  const r = run();
  assert.equal(r.result, true);
  assert.equal(r.set.length, 1);
  assert.ok(fs.existsSync(r.paths[0]));
});
test('packaged run makes no call', () => assert.equal(run({ packaged: true }).set.length, 0));
test('non-darwin run makes no call', () => assert.equal(run({ platform: 'linux' }).set.length, 0));
test('an unloadable image warns once and does not throw', () => {
  const r = run({ empty: true });
  assert.equal(r.set.length, 0);
  assert.equal(r.warns.length, 1);
});
