
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal-session-bind.js'), 'utf8');

function announceWith(current) {
    const heard = [];
    const sandbox = {
        console: { log() {}, warn() {} },
        CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init.detail; } },
        dispatchEvent(event) { heard.push(event.detail); return true; },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(SRC, sandbox);
    const controller = {
        _currentSession: current,
        _unwrapSession(s) { return (s && s.session && typeof s.session === 'object') ? s.session : (s || {}); },
        _currentTmuxName() { return current.tmux_session || (current.session || {}).tmux_session || null; },
    };
    sandbox.TerminalController = controller;
    sandbox.TerminalSessionBind.announce(controller, 'ses_a');
    return heard[0] || null;
}

let failures = 0;
function test(name, fn) {
    try { fn(); console.log(`ok - ${name}`); } catch (err) { failures += 1; console.log(`not ok - ${name}\n  ${err.message}`); }
}

test('a wrapper carries the inner session epoch', () => {
    const detail = announceWith({ tmux_session: 'cloude_a', session: { id: 'ses_a', tmux_session: 'cloude_a', tmux_created_epoch: 100 } });
    assert.equal(detail.tmuxName, 'cloude_a');
    assert.equal(detail.tmuxEpoch, 100);
});

test('a bare session (create, adopt) carries its own epoch', () => {
    const detail = announceWith({ id: 'ses_a', tmux_session: 'cloude_a', tmux_created_epoch: 200 });
    assert.equal(detail.tmuxEpoch, 200);
});

test('an absent or non-numeric epoch is null, never a guess', () => {
    assert.equal(announceWith({ id: 'ses_a', tmux_session: 'cloude_a' }).tmuxEpoch, null);
    assert.equal(announceWith({ id: 'ses_a', tmux_session: 'cloude_a', tmux_created_epoch: '100' }).tmuxEpoch, null);
    assert.equal(announceWith({ id: 'ses_a', tmux_session: 'cloude_a', tmux_created_epoch: null }).tmuxEpoch, null);
});

if (failures) { console.log(`${failures} failed`); process.exit(1); }
console.log('all passed');
