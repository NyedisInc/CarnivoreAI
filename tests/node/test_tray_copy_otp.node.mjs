import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const macDir = path.join(import.meta.dirname, '..', '..', 'macOS');
const { handlers } = require(path.join(macDir, 'tray-menu', 'actions', 'phone.js'));

const ENV_CODE = '111111';
const LOADED_CODE = '222222';

/* context with a */
function makeCtx(answer) {
  const out = { clipboard: [], dialogs: [], asked: [] };
  const ctx = {
    t: (key) => key,
    qrWindow: require(path.join(macDir, 'qr-window.js')),
    getTray: () => null,
    refresh() {},
    clipboard: { writeText: (text) => out.clipboard.push(text) },
    dialog: { showErrorBox: (title, body) => out.dialogs.push([title, body]) },
    serverManager: { getCurrentOtp: () => ENV_CODE, getPort: () => 8123, getProjectRoot: () => os_tmp() },
    data: { api: () => ({ getAuthed: async (route, opts) => { out.asked.push([route, opts && opts.baseUrl]); return answer; } }) },
  };
  return { ctx, out };
}
const os_tmp = () => import.meta.dirname;
const ok = (data) => ({ reachable: true, status: 200, data, error: null });

test('copy otp: the code comes from the running server, not .env (#2712)', async () => {
  const { ctx, out } = makeCtx(ok({ code: LOADED_CODE, restart_pending: false }));
  await handlers(ctx)['phone.copy_otp']();
  assert.deepEqual(out.clipboard, [LOADED_CODE]);
  assert.ok(!out.clipboard.includes(ENV_CODE), 'the .env code is never copied');
  assert.deepEqual(out.asked, [['/api/v1/auth/enrollment/loaded/code', 'http://127.0.0.1:8123']]);
});

test('copy otp: a pending restart copies nothing and says restart needed (#2712)', async () => {
  const { ctx, out } = makeCtx(ok({ code: null, restart_pending: true }));
  await handlers(ctx)['phone.copy_otp']();
  assert.deepEqual(out.clipboard, []);
  assert.equal(out.dialogs.length, 1);
  assert.equal(out.dialogs[0][1], 'menubar.otp.restart_pending');
});

test('copy otp: every failed ask copies nothing and names its state (#2712)', async () => {
  const cases = [[0, 'offline'], [401, 'restart_needed'], [403, 'loopback_only'], [429, 'rate_limited'], [500, 'refused']];
  for (const [status, state] of cases) {
    const { ctx, out } = makeCtx({ reachable: false, status, data: null, error: 'x' });
    await handlers(ctx)['phone.copy_otp']();
    assert.deepEqual(out.clipboard, [], `${state}: nothing copied`);
    assert.equal(out.dialogs[0][1], `menubar.qr.failure.${state}`);
  }
  const { ctx, out } = makeCtx(ok({ restart_pending: false }));
  await handlers(ctx)['phone.copy_otp']();
  assert.deepEqual(out.clipboard, []);
  assert.equal(out.dialogs[0][1], 'menubar.qr.failure.refused');
});

test('copy otp: dialog title and tooltip come from the catalog (#2712)', async () => {
  const { ctx, out } = makeCtx({ reachable: false, status: 0, data: null, error: 'x' });
  await handlers(ctx)['phone.copy_otp']();
  assert.equal(out.dialogs[0][0], 'menubar.otp.error_title');
  const tips = [];
  const ok2 = makeCtx(ok({ code: LOADED_CODE, restart_pending: false }));
  ok2.ctx.getTray = () => ({ setToolTip: (t) => tips.push(t) });
  await handlers(ok2.ctx)['phone.copy_otp']();
  assert.deepEqual(tips, ['menubar.otp.copied']);
});

test('copy otp label: no code on it, shown when not joined and setup is not incomplete (#2712)', () => {
  const { phoneMenu } = require(path.join(macDir, 'tray-menu', 'model', 'phone.js'));
  const t = (key) => key;
  const find = (snap) => phoneMenu(snap, { t }).submenu.find((i) => i.id === 'phone.copy_otp');
  const on = find({ joined: false, phone: { otpAvailable: true } });
  assert.equal(on.label, 'menubar.phone.copy_otp');
  assert.ok(!on.sublabel && on.enabled !== false);
  assert.equal(find({ joined: false, phone: { otpAvailable: false } }).enabled, false);
  assert.equal(find({ joined: true, phone: {} }), undefined);
});

test('copy otp: both codes spent says so and is not a refusal (#2712)', async () => {
  const { ctx, out } = makeCtx(ok({ code: null, restart_pending: false }));
  await handlers(ctx)['phone.copy_otp']();
  assert.deepEqual(out.clipboard, []);
  assert.equal(out.dialogs[0][1], 'menubar.otp.no_code_free');
});
