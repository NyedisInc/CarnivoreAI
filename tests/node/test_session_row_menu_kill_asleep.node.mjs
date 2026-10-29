import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const dir = path.dirname(fileURLToPath(import.meta.url));
const src = fs.readFileSync(path.join(dir, '..', '..', 'client', 'js', 'session-row-menu-sleep.js'), 'utf8');

function env({ confirm, killImpl }) {
    const calls = { confirm: [], kill: [], said: [], refresh: 0 };
    const win = {
        App: { showConfirmModal: async (...a) => { calls.confirm.push(a); return confirm; } },
        API: { killAsleepSession: async (u) => { calls.kill.push(u); return killImpl(); } },
        SessionRowMenuActions: { say: (_c, t) => calls.said.push(t) },
        SessionSidebar: { _fetchAndRender: async () => { calls.refresh++; } },
    };
    win.window = win;
    win.globalThis = win;
    win.CloudeI18n = { t: (k, p) => k + (p ? JSON.stringify(p) : '') };
    vm.runInNewContext(src, win);
    return { sleeper: win.SessionRowMenuSleep, calls };
}
const ctx = { name: 'carnivore_a', label: 'agent a', sessionUuid: 'u-1', asleep: true };
let failed = 0;
async function t(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (e) { console.log(`NOT OK - ${name}`); console.error(e); failed++; }
}

await t('confirm then DELETE, danger styled, names the agent', async () => {
    const { sleeper, calls } = env({ confirm: true, killImpl: async () => ({}) });
    assert.equal(await sleeper.runKillAsleep(ctx), true);
    assert.deepEqual(calls.kill, ['u-1']);
    assert.equal(calls.confirm[0][5], 'danger');
    assert.match(calls.confirm[0][1], /agent a/);
    assert.equal(calls.refresh, 1);
});
await t('cancel calls nothing', async () => {
    const { sleeper, calls } = env({ confirm: false, killImpl: async () => ({}) });
    assert.equal(await sleeper.runKillAsleep(ctx), false);
    assert.deepEqual(calls.kill, []);
});
await t('a refusal is said and the list still refreshes', async () => {
    const { sleeper, calls } = env({ confirm: true, killImpl: async () => { throw new Error('not asleep'); } });
    assert.equal(await sleeper.runKillAsleep(ctx), false);
    assert.match(calls.said[0], /not asleep/);
    assert.equal(calls.refresh, 1);
});
process.exit(failed ? 1 : 0);
