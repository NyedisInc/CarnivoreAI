// (this repo has no package.json / jest).
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

import { glyphSvg } from '../client/js/icons/glyphs.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function readClientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

let failures = 0;
let passes = 0;
const queue = [];

function test(name, fn) {
    queue.push({ name, fn });
}

async function runQueue() {
    for (const { name, fn } of queue) {
        try {
            await fn();
            passes += 1;
            console.log(`  PASS  ${name}`);
        } catch (err) {
            failures += 1;
            console.log(`  FAIL  ${name}`);
            console.log(`        ${err && err.message}`);
        }
    }
}

function loadModules() {
    const confirmCalls = [];
    const sandbox = {
        console: { log() {}, error() {}, warn() {} },
        document: {
            createElement() {
                let text = '';
                return {
                    set textContent(v) {
                        text = String(v)
                            .replace(/&/g, '&amp;')
                            .replace(/</g, '&lt;')
                            .replace(/>/g, '&gt;');
                    },
                    get innerHTML() {
                        return text;
                    },
                };
            },
        },
    };
    sandbox.window = sandbox;
    // publishes it in a browser. Every icon in session-status-ui.js reads
    // its coordinates from `globalThis.CloudeGlyphs` at call time, so a
    sandbox.CloudeGlyphs = { glyphSvg };
    sandbox.globalThis = sandbox;
    sandbox.window.App = {
        showConfirmModal(...args) {
            confirmCalls.push(args);
            return Promise.resolve(true);
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(readClientJs('session-status-ui.js'), sandbox);
    vm.runInContext(readClientJs('session-row-actions-confirm.js'), sandbox);
    vm.runInContext(readClientJs('session-row-actions.js'), sandbox);
    sandbox.window.__confirmCalls = confirmCalls;
    return sandbox.window;
}

function local(arr) {
    return Array.from(arr);
}

function buttonCount(markup) {
    return (markup.match(/<button/g) || []).length;
}

function actionsIn(markup) {
    return (markup.match(/data-session-action="([a-z]+)"/g) || []).map((m) =>
        m.replace(/.*="([a-z]+)"/, '$1')
    );
}

// ---------------------------------------------------------------------------

test('a dead row offers restart AND remove, in that order', () => {
    const w = loadModules();
    const actions = local(w.SessionRowActions.actionsFor('dead'));
    assert.deepEqual(actions, [
        w.SessionRowActions.ACTION_RESTART,
        w.SessionRowActions.ACTION_REMOVE,
    ]);
});

test('losing Remove on a dead row would be a regression - it is still there', () => {
    const w = loadModules();
    assert.ok(
        local(w.SessionRowActions.actionsFor('dead')).indexOf(
            w.SessionRowActions.ACTION_REMOVE
        ) !== -1,
        'remove disappeared from the dead row'
    );
});

test('a running row offers close FIRST and then restart', () => {
    const w = loadModules();
    for (const status of ['working', 'idle', 'question', 'working_subagent']) {
        const actions = local(w.SessionRowActions.actionsFor(status));
        assert.deepEqual(
            actions,
            [w.SessionRowActions.ACTION_CLOSE, w.SessionRowActions.ACTION_RESTART],
            status,
        );
    }
});

test('unknown status is never treated as dead', () => {
    const w = loadModules();
    assert.deepEqual(local(w.SessionRowActions.actionsFor(undefined)), [
        w.SessionRowActions.ACTION_CLOSE,
    ]);
    assert.deepEqual(local(w.SessionRowActions.actionsFor('unknown')), [
        w.SessionRowActions.ACTION_CLOSE,
    ]);
});


test('THE VISIBLE DEFECT: dead-row markup renders two buttons', () => {
    const w = loadModules();
    const markup = w.SessionRowActions.html('dead', 'my-session', 'surface');
    assert.equal(
        buttonCount(markup),
        2,
        `expected restart + remove, got markup: ${markup}`
    );
    assert.deepEqual(local(actionsIn(markup)), ['restart', 'remove']);
});

test('a running row renders close then restart, an unknown one close alone', () => {
    const w = loadModules();
    const live = w.SessionRowActions.html('working', 'my-session', 'surface');
    assert.equal(buttonCount(live), 2, live);
    assert.deepEqual(local(actionsIn(live)), ['close', 'restart']);

    // could not be read
    const unread = w.SessionRowActions.html('unknown', 'my-session', 'surface');
    assert.equal(buttonCount(unread), 1, unread);
    assert.deepEqual(local(actionsIn(unread)), ['close']);
});

test('the restart button carries a real glyph, not an empty control', () => {
    const w = loadModules();
    const markup = w.SessionRowActions.html('dead', 'x', 'surface');
    const restart = markup
        .split('</button>')
        .find((s) => s.indexOf('data-session-action="restart"') !== -1);
    assert.ok(restart, 'no restart button in the markup at all');
    assert.ok(
        restart.indexOf('<svg') !== -1,
        'restart button rendered with no icon at all'
    );
    assert.ok(
        restart.indexOf('<path') !== -1,
        'restart icon has no drawn path - it would render as a blank box'
    );
});

test('restart and remove use DIFFERENT glyphs', () => {
    const w = loadModules();
    const ui = w.SessionStatusUI;
    assert.notEqual(
        ui.restartIconSvg(),
        ui.trashIconSvg(),
        'restart and remove would be indistinguishable'
    );
    assert.notEqual(ui.restartIconSvg(), ui.closeIconSvg());
});

test('both dead-row buttons carry an aria-label; only remove adds a matching hover title (#1686)', () => {
    const w = loadModules();
    const markup = w.SessionRowActions.html('dead', 'x', 'surface');
    const buttons = markup.split('</button>').filter((s) => s.indexOf('<button') !== -1);
    assert.equal(buttons.length, 2);
    for (const b of buttons) {
        const title = /title="([^"]*)"/.exec(b);
        const aria = /aria-label="([^"]*)"/.exec(b);
        assert.ok(aria && aria[1].trim(), `no aria-label: ${b}`);
        if (aria[1] === 'remove from the list') {
            assert.ok(title && title[1].trim(), `no title: ${b}`);
            assert.equal(title[1], aria[1], 'title and aria-label drifted');
        } else {
            assert.equal(title, null, `the restart arrow is self-evident and draws no tip: ${b}`);
        }
    }
});

test('the session name is escaped in every button, not just the first', () => {
    const w = loadModules();
    const markup = w.SessionRowActions.html('dead', 'a"b<c', 'surface');
    assert.equal(markup.indexOf('a"b<c'), -1, 'raw name leaked into an attribute');
    assert.equal(
        (markup.match(/data-session-name="a&quot;b&lt;c"/g) || []).length,
        2,
        'the escaped name is not on both buttons'
    );
});


test('restart does NOT prompt for confirmation, because it destroys nothing', async () => {
    const w = loadModules();
    assert.equal(
        typeof w.SessionRowActions.requiresConfirm,
        'function',
        'no requiresConfirm() to state the policy'
    );
    assert.equal(w.SessionRowActions.requiresConfirm('restart'), false);
    assert.equal(w.SessionRowActions.requiresConfirm('remove'), true);
    assert.equal(w.SessionRowActions.requiresConfirm('close'), true);
});

test('remove still confirms, and its copy still names the uploads bucket', async () => {
    const w = loadModules();
    await w.SessionRowActions.confirm('remove', 'my-session');
    const calls = w.__confirmCalls;
    assert.equal(calls.length, 1, 'remove stopped confirming');
    assert.ok(
        calls[0].join(' ').indexOf('uploads folder') !== -1,
        'remove copy no longer names what it deletes'
    );
});


test('the old singular actionFor() still answers, so no call site breaks', () => {
    const w = loadModules();
    assert.equal(typeof w.SessionRowActions.actionFor, 'function');
    assert.equal(w.SessionRowActions.actionFor('working'), 'close');
    assert.equal(w.SessionRowActions.actionFor('dead'), 'restart');
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
