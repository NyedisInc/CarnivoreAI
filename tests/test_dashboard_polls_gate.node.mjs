// the home screen
// the home screen
// gives the same
// Exits 0 and prints ALL PASS on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function readClientJs(relative) {
    return fs.readFileSync(path.join(ROOT, 'client', 'js', relative), 'utf8');
}

function makeScreen() {
    const classes = new Set();
    return {
        classList: {
            add(c) { classes.add(c); },
            remove(c) { classes.delete(c); },
            contains(c) { return classes.has(c); },
        },
    };
}

function load() {
    const calls = [];
    const screens = {
        'launchpad-screen': makeScreen(),
        'terminal-screen': makeScreen(),
    };
    const body = makeScreen();

    const doc = {
        readyState: 'complete',
        body,
        getElementById(id) { return screens[id] || null; },
        addEventListener() {},
    };

    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: doc,
        CloudeWeb: {
            resumeHomePolls() { calls.push('resume'); },
            pauseHomePolls() { calls.push('pause'); },
            mountTerminalGrid() { return true; },
            unmountTerminalGrid() {},
        },
        setTimeout: () => 0,
        clearTimeout() {},
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    const ctx = vm.createContext(sandbox);

    vm.runInContext(readClientJs('dashboard-polls.js'), ctx, { filename: 'dashboard-polls.js' });
    vm.runInContext(readClientJs('launchpad-host.js'), ctx, { filename: 'launchpad-host.js' });
    vm.runInContext(readClientJs('terminal-grid-host.js'), ctx, { filename: 'terminal-grid-host.js' });

    function setScreen(id) {
        for (const key of Object.keys(screens)) {
            if (key === id) screens[key].classList.add('active');
            else screens[key].classList.remove('active');
        }
    }

    return { ctx, calls, screens, setScreen };
}

function settle(screenId, terminalFirst) {
    const { ctx, calls, setScreen } = load();
    setScreen('launchpad-screen');
    ctx.LaunchpadHost.enter();
    calls.length = 0;

    setScreen(screenId);
    const home = () => {
        if (screenId === 'launchpad-screen') ctx.LaunchpadHost.enter();
        else ctx.LaunchpadHost.exit();
    };
    const terminal = () => ctx.TerminalGridHost.apply();
    if (terminalFirst) { terminal(); home(); } else { home(); terminal(); }
    return calls.length ? calls[calls.length - 1] : 'none';
}

test('the terminal screen keeps the polled reads running, in BOTH host orders', () => {
    assert.equal(settle('terminal-screen', false), 'resume',
        'home host first: the terminal screen must end up polling');
    assert.equal(settle('terminal-screen', true), 'resume',
        'terminal host first: the terminal screen must end up polling');
});

test('coming back to the home screen keeps them running, in BOTH host orders', () => {
    assert.equal(settle('launchpad-screen', false), 'resume');
    assert.equal(settle('launchpad-screen', true), 'resume');
});

test('a screen that is neither still stops them, in BOTH host orders', () => {
    assert.equal(settle(null, false), 'pause',
        'the archive and the auth screen read none of these endpoints');
    assert.equal(settle(null, true), 'pause');
});

test('the gate is read out of the document, not out of the transition', () => {
    const { ctx, screens } = load();
    screens['terminal-screen'].classList.add('active');
    assert.equal(ctx.DashboardPolls.wanted(), true);
    screens['terminal-screen'].classList.remove('active');
    assert.equal(ctx.DashboardPolls.wanted(), false);
    screens['launchpad-screen'].classList.add('active');
    assert.equal(ctx.DashboardPolls.wanted(), true);
});

test('a second sync in the same state is a no-op, not a second burst', () => {
    const { ctx, calls, setScreen } = load();
    setScreen('terminal-screen');
    ctx.DashboardPolls.sync();
    calls.length = 0;
    ctx.DashboardPolls.sync();
    assert.ok(!calls.includes('pause'), 'a repeat sync must not pause a live screen');
});

test('a bundle that has not evaluated yet is not an error', () => {
    const { ctx } = load();
    ctx.CloudeWeb = undefined;
    ctx.DashboardPolls.sync();
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures === 0) console.log('ALL PASS');
process.exit(failures === 0 ? 0 : 1);
