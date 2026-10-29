import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { createEngineDialogs } = require(path.join(here, '..', '..', 'macOS', 'engine', 'engine-dialogs.js'));

test('every engine dialog activates the app first, and a throwing activate never blocks the dialog', async () => {
  const order = [];
  const dialog = { showMessageBox: async () => { order.push('dialog'); return { response: 0 }; } };
  const loadTranslator = async () => (key) => key;
  const dialogs = createEngineDialogs({ dialog, loadTranslator, activate: () => order.push('activate') });
  await dialogs.askRestart({ runningVersion: '1.0.0', bundleVersion: '2.0.0' });
  await dialogs.showRestartFailed('x');
  await dialogs.showStopFailed('x');
  assert.deepEqual(order, ['activate', 'dialog', 'activate', 'dialog', 'activate', 'dialog']);
  const quiet = [];
  const shaky = createEngineDialogs({ dialog: { showMessageBox: async () => { quiet.push('dialog'); return { response: 1 }; } }, loadTranslator,
    activate: () => { throw new Error('no focus'); } });
  assert.equal(await shaky.askRestart({ bundleVersion: '2.0.0' }), 'quit');
  assert.deepEqual(quiet, ['dialog']);
});
