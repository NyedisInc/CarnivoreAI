
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..');

let passes = 0;
let failures = 0;

async function test(name, fn) {
    try {
        await fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function el() {
    return {
        classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
        addEventListener() {}, removeEventListener() {},
        style: {}, dataset: {},
        setAttribute() {}, removeAttribute() {}, getAttribute: () => null,
        focus() {}, click() {}, remove() {}, appendChild() {}, closest: () => null,
        querySelector: () => null, querySelectorAll: () => [],
        set textContent(v) { this._t = String(v); },
        get textContent() { return this._t || ''; },
        set innerHTML(v) { this._h = String(v); },
        get innerHTML() { return this._h || ''; },
    };
}

function load() {
    const opens = [];
    const state = { open: 0, maxConcurrent: 0 };
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: {
            createElement: el, addEventListener() {}, removeEventListener() {},
            getElementById: () => el(), querySelector: () => el(),
            querySelectorAll: () => [], body: el(), documentElement: el(),
        },
        setTimeout, clearTimeout, setInterval: () => 0, clearInterval,
        localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
        location: { href: '', search: '', reload() {} },
        history: { replaceState() {} },
        navigator: { userAgent: '' },
        addEventListener() {}, removeEventListener() {},
        fetch: () => Promise.reject(new Error('no network in this harness')),
        WebSocket: function WebSocketShim() { this.close = () => {}; },
        CloudeI18n: { t: (key) => key },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);

    for (const m of ['session-label.js', 'session-status-ui.js',
        'session-row-actions-confirm.js', 'session-row-actions.js',
        'app.js', 'terminal-client-factory.js', 'terminal.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(ROOT, 'client', 'js', m), 'utf8'),
            sandbox, { filename: m });
    }

    sandbox.App.showConfirmModal = async function (...args) {
        state.open += 1;
        state.maxConcurrent = Math.max(state.maxConcurrent, state.open);
        opens.push(args.slice(0, 2));
        await new Promise((r) => setTimeout(r, 1));
        state.open -= 1;
        return true;
    };

    const tc = sandbox.TerminalController;
    tc.sessionActive = true;
    tc._currentTmuxName = () => 'cloude_demo';
    tc._currentSession = { id: 'sess-1' };
    tc._sessionId = () => 'sess-1';
    tc.updateStatus = () => {};
    tc.stopReconnecting = () => {};
    sandbox.API = { destroySession: () => Promise.resolve({}) };
    sandbox.Auth = { logout() { sandbox.__loggedOut = true; } };

    return { sandbox, opens, state };
}

await test('the harness can actually observe a dialog (positive control)', async () => {
    const { sandbox, opens } = load();
    await sandbox.App.showConfirmModal('probe', 'probe body');
    assert.equal(opens.length, 1,
        'the instrumented confirm recorded nothing - every count below '
        + 'would pass for the wrong reason');
});

await test('logging out with an active session raises exactly ONE confirmation', async () => {
    const { sandbox, opens, state } = load();
    await sandbox.App.logout();
    assert.equal(opens.length, 1,
        `expected 1 confirmation for one logout, got ${opens.length}: `
        + JSON.stringify(opens));
    assert.equal(state.maxConcurrent, 1,
        'confirmations must never be on screen at the same time');
    assert.equal(sandbox.__loggedOut, true,
        'the logout must still complete after the single confirmation');
});

await test('the one dialog shown is the LOGOUT question, not the close-session one', async () => {
    const { sandbox, opens } = load();
    await sandbox.App.logout();
    assert.ok(opens.length >= 1, 'no dialog was raised at all');
    assert.match(String(opens[0][1]), /logout/i,
        `the surviving dialog must be the logout question, got: ${JSON.stringify(opens[0])}`);
});

await test('the session is still actually destroyed on logout', async () => {
    const { sandbox } = load();
    let destroyed = null;
    sandbox.API = { destroySession: (id) => { destroyed = id ?? 'default'; return Promise.resolve({}); } };
    await sandbox.App.logout();
    assert.ok(destroyed !== null,
        'removing the redundant dialog must not remove the teardown it gated');
});

await test('a DIRECT destroySession still confirms - the sidebar depends on it', async () => {
    const { sandbox, opens } = load();
    await sandbox.TerminalController.destroySession(
        sandbox.SessionRowActions.ACTION_CLOSE);
    assert.equal(opens.length, 1,
        'the sidebar own-tab path delegates here precisely because this '
        + 'method owns the confirm; it must keep owning it');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
