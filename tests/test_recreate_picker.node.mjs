// (this repo has no package.json / jest).
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

function load(api) {
    const sandbox = {
        console: { log() {}, error() {}, warn() {} },
        document: {
            createElement() {
                let text = '';
                return {
                    set textContent(v) { text = String(v); },
                    get innerHTML() { return text; },
                };
            },
        },
    };
    sandbox.window = sandbox;
    sandbox.API = api;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(
            path.join(__dirname, '..', 'client', 'js',
                'session-restart-options.js'),
            'utf8',
        ),
        sandbox,
    );
    return sandbox.window;
}

const GONE = {
    pane_state: 'unknown',
    unchanged: { kind: 'cannot_determine', detail: 'the pane could not be read' },
    options: [],
};

const LIVE = {
    pane_state: 'alive',
    unchanged: { kind: 'not_dead', detail: 'still running' },
    options: [],
};

const DEAD_PANE = {
    pane_state: 'dead',
    unchanged: { kind: 'agent', detail: 'would start the agent' },
    options: [],
};

test('a pane that could not be read is re-asked as a recreate', () => {
    const w = load({});
    assert.equal(w.SessionRestartOptions.shouldRecreate(GONE), true);
});

test('A LIVE SESSION IS NEVER RE-ASKED', () => {
    const w = load({});
    assert.equal(w.SessionRestartOptions.shouldRecreate(LIVE), false);
    assert.equal(
        w.SessionRestartOptions.shouldRecreate(
            { pane_state: 'alive', unchanged: { kind: 'cannot_determine' } }),
        false,
        'alive is a measurement and outranks an undetermined rung',
    );
});

test('a dead PANE keeps the respawn path it already had', () => {
    const w = load({});
    assert.equal(w.SessionRestartOptions.shouldRecreate(DEAD_PANE), false);
});

test('a missing preview is never re-asked', () => {
    const w = load({});
    assert.equal(w.SessionRestartOptions.shouldRecreate(null), false);
    assert.equal(w.SessionRestartOptions.shouldRecreate({}), false);
});

test('recreate is an actionable rung and carries its own badge', () => {
    const w = load({});
    assert.equal(w.SessionRestartOptions.isActionable('recreate'), true);
    const badge = w.SessionRestartOptions.KIND_TAG.recreate;
    assert.ok(badge && badge.length, 'the rung needs a tag of its own');
    assert.notEqual(
        badge, w.SessionRestartOptions.KIND_TAG.agent,
        'agent reuses the pane and keeps its scrollback; recreate does not',
    );
});

test('an unknown rung is still refused', () => {
    const w = load({});
    assert.equal(w.SessionRestartOptions.isActionable('brand_new_rung'), false);
});

test('previewFor returns the restart answer and mode for a live row',
    async () => {
        const w = load({
            restartPreview: async () => LIVE,
            recreatePreview: async () => { throw new Error('must not be asked'); },
        });
        const answer = await w.SessionRestartOptions.previewFor('cloude_a', 'row-uuid');
        assert.equal(answer.mode, 'restart');
        assert.equal(answer.preview.unchanged.kind, 'not_dead');
    });

test('previewFor asks the recreate endpoint for an unreadable pane',
    async () => {
        let asked = null;
        const RECREATED = {
            pane_state: 'dead',
            unchanged: { kind: 'cannot_determine', detail: 'pick a wrapper' },
            options: [{
                agent_type: 'claude', label: 'claude', kind: 'recreate',
                actionable_now: true, detail: 'would build a new session',
            }],
        };
        const w = load({
            restartPreview: async () => GONE,
            recreatePreview: async (uuid) => { asked = uuid; return RECREATED; },
        });
        const answer = await w.SessionRestartOptions.previewFor('cloude_a', 'row-uuid');
        assert.equal(asked, 'row-uuid',
            'the recreate endpoints take the durable key, not the name');
        assert.equal(answer.mode, 'recreate',
            'the mode names the endpoint the action must post to');
        assert.equal(answer.preview.options[0].kind, 'recreate');
    });

test('a failed recreate ask falls back to the first answer, not to nothing',
    async () => {
        const w = load({
            restartPreview: async () => GONE,
            recreatePreview: async () => { throw new Error('offline'); },
        });
        const answer = await w.SessionRestartOptions.previewFor('cloude_a', 'row-uuid');
        assert.equal(answer.mode, 'restart');
        assert.equal(answer.preview.unchanged.kind, 'cannot_determine',
            'the honest refusal is shown rather than a blank panel');
    });

test('an API with no recreate method degrades to the old behaviour',
    async () => {
        const w = load({ restartPreview: async () => GONE });
        const answer = await w.SessionRestartOptions.previewFor('cloude_a', 'row-uuid');
        assert.equal(answer.mode, 'restart');
    });


test('WITHOUT A DURABLE KEY THE SECOND QUESTION IS NEVER ASKED',
    async () => {
        const w = load({
            restartPreview: async () => GONE,
            recreatePreview: async () => { throw new Error('must not be asked'); },
        });
        const answer = await w.SessionRestartOptions.previewFor('cloude_a', null);
        assert.equal(answer.mode, 'restart');
        assert.equal(answer.sessionUuid, null);
    });

test('recreateTarget names a row only when exactly one carries the name',
    () => {
        const w = load({});
        const t = w.SessionRestartOptions.recreateTarget;
        const rows = [
            { tmux_name: 'cloude_a', session_uuid: 'u1' },
            { tmux_name: 'cloude_b', session_uuid: 'u2' },
        ];
        assert.equal(t(rows, 'cloude_a'), 'u1');
        assert.equal(t(rows, 'cloude_missing'), null);
        assert.equal(t(null, 'cloude_a'), null);
        assert.equal(t(rows, ''), null);
    });

test('TWO ROWS SHARING A NAME REFUSE RATHER THAN PICK THE NEWEST', () => {
    const w = load({});
    const rows = [
        { tmux_name: 'cloude_a', session_uuid: 'older' },
        { tmux_name: 'cloude_a', session_uuid: 'newer' },
    ];
    assert.equal(w.SessionRestartOptions.recreateTarget(rows, 'cloude_a'), null);
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures === 0) console.log('ALL PASS');
process.exit(failures === 0 ? 0 : 1);
