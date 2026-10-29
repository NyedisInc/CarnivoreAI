import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = fs.readFileSync(path.join(root, 'client/js/session-restart-return.js'), 'utf8');

function load(holds) {
    const calls = { began: 0, returned: 0 };
    const win = {
        CloudeWeb: { layoutPage: { holds: () => holds } },
        NavigationGeneration: { begin() { calls.began++; return 1; }, keep: () => true },
        CloudeTerminal: { SCROLLBACK_ROWS: 5000 },
        API: { getSession: async () => ({ session: { id: 'ses_a' } }) },
        App: { returnToExistingTerminal() { calls.returned++; } },
    };
    win.window = win;
    vm.runInNewContext(src, { window: win, console: { log() {} } });
    return { reopen: win.SessionRestartReturn.reopen, calls };
}

{
    const { reopen, calls } = load(true);
    const back = await reopen({ session_id: 'ses_a', name: 'carnivore_a' });
    assert.equal(back.status, 'reopened');
    assert.equal(calls.began, 0, 'a held session must not begin a navigation');
    assert.equal(calls.returned, 0, 'a held session must not be shown full screen');
}
{
    const { reopen, calls } = load(false);
    const back = await reopen({ session_id: 'ses_a', name: 'carnivore_a' });
    assert.equal(back.status, 'reopened');
    assert.equal(calls.returned, 1, 'a session outside a layout is still reopened');
}
console.log('ALL PASS');
