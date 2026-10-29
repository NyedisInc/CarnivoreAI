// (this repo has no package.json / jest).
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { rowsHtml } from './helpers/launch_choice_fake.mjs';

function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;
const queue = [];

function test(name, fn) {
    queue.push({ name, fn });
}

function runQueue() {
    for (const { name, fn } of queue) {
        try {
            fn();
            passes += 1;
            console.log(`  PASS  ${name}`);
        } catch (err) {
            failures += 1;
            console.log(`  FAIL  ${name}`);
            console.log(`        ${err && err.message}`);
        }
    }
}

function load(names) {
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
    vm.createContext(sandbox);
    for (const name of names) {
        vm.runInContext(
            fs.readFileSync(
                path.join(__dirname, '..', 'client', 'js', name),
                'utf8',
            ),
            sandbox,
        );
    }
    return sandbox.window;
}

function livePreview(projectedKind) {
    return {
        name: 'row-live',
        current_agent_type: null,
        pane_state: 'alive',
        unchanged: {
            kind: 'not_dead',
            detail: 'this session is still running; there is nothing to restart',
            actionable: false,
        },
        projected: {
            kind: projectedKind || 'shell',
            detail: projectedKind === 'agent'
                ? 'restarting the agent this session was launched with'
                : 'this pane was opened as a plain shell; restarting opens one again',
            actionable: true,
        },
        options: [
            {
                agent_type: 'claude-chrome',
                label: 'claude-chrome',
                is_current: false,
                resolvable: true,
                actionable_now: false,
                kind: 'not_dead',
                detail: 'this session is still running',
                projected_kind: 'agent',
                projected_detail: 'starting claude-chrome, which you picked',
                command: 'run-cc',
            },
        ],
        wrappers_status: 'ok',
    };
}

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('a live row offers restart alongside close', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    for (const status of ['working', 'working_subagent', 'question',
        'finished_unread', 'idle', 'running']) {
        const actions = plain(A.actionsFor(status));
        assert.deepEqual(
            actions,
            [A.ACTION_CLOSE, A.ACTION_RESTART],
            `${status} does not offer restart: ${JSON.stringify(actions)}`,
        );
    }
});

test('a dead row is exactly what it was', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    assert.deepEqual(
        plain(A.actionsFor('dead')), [A.ACTION_RESTART, A.ACTION_REMOVE]);
    assert.equal(A.actionFor('dead'), A.ACTION_RESTART);
});

test('an unknown row NOT known to be ours is never offered restart', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    for (const status of [undefined, null, 'unknown', 'not_a_real_status']) {
        for (const facts of [undefined, null, {}, { owned: false }, { owned: 'yes' }]) {
            assert.deepEqual(
                plain(A.actionsFor(status, facts)),
                [A.ACTION_CLOSE],
                `restart offered on an unreadable status: ${String(status)} `
                    + `with facts ${JSON.stringify(facts)}`,
            );
        }
    }
});

test('an unknown row WE CREATED is offered restart after close (owner, 2026-09-22)', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    for (const status of [undefined, null, 'unknown', 'not_a_real_status']) {
        assert.deepEqual(
            plain(A.actionsFor(status, { owned: true })),
            [A.ACTION_CLOSE, A.ACTION_RESTART],
            `an owned unknown row (${String(status)}) must offer restart`,
        );
    }
    assert.equal(A.offersMenu('unknown'), true);
});

test('ownership changes nothing for a live, dead or stopped row', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    for (const status of ['working', 'idle', 'question', 'dead', 'stopped']) {
        for (const owned of [true, false]) {
            assert.deepEqual(
                plain(A.actionsFor(status, { owned })),
                plain(A.actionsFor(status)),
                `ownership moved the answer for ${status} (owned=${owned})`,
            );
        }
    }
});

test('a stopped row is not treated as a live one', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    assert.ok(A.LIVE_STATUSES.indexOf('stopped') === -1);
    assert.ok(A.LIVE_STATUSES.indexOf('dead') === -1);
    assert.ok(A.LIVE_STATUSES.indexOf('unknown') === -1);
});

test('the restart control still needs no generic confirm dialog', () => {
    const w = load(['session-status-ui.js', 'session-row-actions-confirm.js', 'session-row-actions.js']);
    const A = w.SessionRowActions;
    assert.equal(A.requiresConfirm(A.ACTION_RESTART), false);
    assert.equal(A.requiresConfirm(A.ACTION_CLOSE), true);
    assert.equal(A.requiresConfirm(A.ACTION_REMOVE), true);
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

test('the arm control is emitted unchecked by default and takes no payload field', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    const html = w.SessionRestartLive.armHtml();
    assert.ok(html.includes('type="checkbox"'), 'the arm control is not a checkbox');
    assert.ok(
        !/\schecked/.test(html),
        `the arm control arrives already armed: ${html}`,
    );
    assert.ok(
        !html.includes('restart-picker__arm-note'),
        'the gesture note rendered with no argument at all',
    );
});

test('ONLY {armedByGesture: true} ticks the box, per issue #441/#1061 (Joe, 2026-09-28)', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    const live = w.SessionRestartLive;

    const armed = live.armHtml({ armedByGesture: true });
    assert.ok(/\schecked\s/.test(armed) || /\schecked>/.test(armed),
        `armedByGesture: true did not tick the box: ${armed}`);
    assert.ok(!armed.includes('restart-picker__arm-note'),
        'a pre-ticked box rendered the removed "armed by shift-click" note');

    for (const shape of [
        undefined, null, {}, { armedByGesture: false },
        { armedByGesture: 'true' }, { armedByGesture: 1 },
        true, 'armedByGesture',
    ]) {
        const html = live.armHtml(shape);
        assert.ok(
            !/\schecked/.test(html),
            `armHtml(${JSON.stringify(shape)}) ticked the box`,
        );
        assert.ok(
            !html.includes('restart-picker__arm-note'),
            `armHtml(${JSON.stringify(shape)}) rendered the gesture note`,
        );
    }
});

test('a live pane paints every radio locked however good the projection', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    for (const projected of ['agent', 'shell', 'replay']) {
        const html = rowsHtml(w.SessionRestartPicker.optionRows(livePreview(projected)));
        const inputs = html.match(/<div role="option"[^>]*>/g) || [];
        assert.equal(inputs.length, 2, `expected 2 options, got ${inputs.length}`);
        for (const tag of inputs) {
            assert.ok(
                /aria-disabled="true"/.test(tag),
                `a projected '${projected}' unlocked a live option: ${tag}`,
            );
            assert.ok(
                /data-actionable-now="0"/.test(tag),
                `the server's permission was not carried through: ${tag}`,
            );
        }
    }
});

test('the two facts ride on separate attributes', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    const html = rowsHtml(w.SessionRestartPicker.optionRows(livePreview('agent')));
    assert.ok(html.includes('data-actionable-now="0"'));
    assert.ok(html.includes('data-live-eligible="1"'));
});

test('a cannot-determine rung is not eligible even when armed', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    const preview = livePreview('agent');
    preview.projected = {
        kind: 'cannot_determine',
        detail: 'tmux did not answer when asked about this pane',
        actionable: false,
    };
    const html = rowsHtml(w.SessionRestartPicker.optionRows(preview));
    const baseline = (html.match(/<div role="option"[^>]*data-choice-option=""[^>]*>/) || [''])[0];
    assert.ok(baseline, 'the baseline option is missing');
    assert.ok(
        /data-live-eligible="0"/.test(baseline),
        `an unreadable pane was marked eligible for a live kill: ${baseline}`,
    );
});

test('a missing transcript is not eligible even when armed', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    const preview = livePreview('agent');
    preview.projected = {
        kind: 'transcript_missing',
        detail: 'the conversation this session would resume has no transcript',
        actionable: false,
    };
    const html = rowsHtml(w.SessionRestartPicker.optionRows(preview));
    const baseline = (html.match(/<div role="option"[^>]*data-choice-option=""[^>]*>/) || [''])[0];
    assert.ok(/data-live-eligible="0"/.test(baseline), baseline);
});

test('the arm control is unticked and says it kills, and no notice carries it', () => {
    const w = load(['session-restart-live.js', 'session-restart-options.js', 'session-restart-picker.js']);
    assert.ok(
        !w.SessionRestartPicker.noticeHtml(livePreview('shell')).includes('restart-picker__arm'),
        'the arm control is still rendered in the notices above the list',
    );
    const arm = w.SessionRestartLive.armHtml();
    assert.ok(!/\schecked/.test(arm), `the arm box arrived ticked: ${arm}`);
    assert.ok(arm.includes('restart-picker-arm-hint'), 'the arm box lost its description');

    const unknown = livePreview('shell');
    unknown.pane_state = 'unknown';
    assert.ok(
        !w.SessionRestartPicker.noticeHtml(unknown).includes('restart-picker__arm'),
        'an unreadable pane was offered a kill-what-is-running control',
    );
});

runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures === 0) console.log('ALL PASS');
process.exit(failures === 0 ? 0 : 1);
