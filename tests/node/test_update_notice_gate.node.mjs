import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const { createUpdateNotice } = require('../../macOS/update-notice.js');

function rig(posting) {
  const calls = { supported: 0, shown: 0, memo: 0 };
  class FakeNotification {
    static isSupported() { calls.supported += 1; return true; }
    on() {}
    show() { calls.shown += 1; }
  }
  const memo = { shouldAnnounce() { calls.memo += 1; return true; } };
  const notice = createUpdateNotice({ Notification: FakeNotification, memo, t: (k) => k, onInstall() {}, bannersPosting: async () => posting });
  return { notice, calls };
}
const ux = { notify: true, menuRow: { version: '1.16.5' } };

test('banners off: no isSupported call, nothing shown, the version is not spent', async () => {
  const { notice, calls } = rig(false);
  assert.equal(await notice.onUx(ux), false);
  assert.deepEqual(calls, { supported: 0, shown: 0, memo: 0 });
});

test('banners on: support checked, the notice shown', async () => {
  const { notice, calls } = rig(true);
  assert.equal(await notice.onUx(ux), true);
  assert.deepEqual(calls, { supported: 1, shown: 1, memo: 1 });
});
