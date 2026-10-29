// (this repo has no package.json / jest).
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import CATALOG from '../client/js/i18n/catalog.en.js';
import { rowsHtml } from './helpers/launch_choice_fake.mjs';

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

function loadPicker() {
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
    sandbox.CloudeI18n = {
        t: (key, params) => (key in CATALOG
            ? String(CATALOG[key]).replace(/\{(\w+)\}/g,
                (m, k) => (params && k in params ? String(params[k]) : m))
            : key),
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const file of ['session-restart-options.js',
        'session-restart-picker.js']) {
        vm.runInContext(
            fs.readFileSync(
                path.join(__dirname, '..', 'client', 'js', file),
                'utf8',
            ),
            sandbox,
        );
    }
    return sandbox.window;
}

const LIVE_OPTION = {
    agent_type: 'claude-chrome',
    label: 'claude-chrome',
    is_current: true,
    resolvable: true,
    actionable_now: false,
    kind: 'not_dead',
    detail: 'this session is still running; there is nothing to restart',
    projected_kind: 'agent',
    projected_detail: 'starting claude-chrome, which you picked',
    command: 'run-cc',
};

const LIVE_PREVIEW = {
    name: 'row-live',
    current_agent_type: 'claude-chrome',
    pane_state: 'alive',
    unchanged: {
        kind: 'not_dead',
        detail: 'this session is still running; there is nothing to restart',
        actionable: false,
    },
    projected: {
        kind: 'shell',
        detail: 'this pane was opened as a plain shell; restarting opens one again',
        actionable: true,
    },
    options: [LIVE_OPTION],
    wrappers_status: 'ok',
};

test('an unrecognised rung is never actionable', () => {
    const w = loadPicker();
    assert.equal(w.SessionRestartPicker.isActionable('agent'), true);
    assert.equal(w.SessionRestartPicker.isActionable('shell'), true);
    assert.equal(w.SessionRestartPicker.isActionable('replay'), true);
    assert.equal(w.SessionRestartPicker.isActionable('not_dead'), false);
    assert.equal(w.SessionRestartPicker.isActionable('cannot_determine'), false);
    assert.equal(w.SessionRestartPicker.isActionable('some_future_rung'), false);
    assert.equal(w.SessionRestartPicker.isActionable(undefined), false);
});

test('a live session projects an agent AND stays unpickable', () => {
    const w = loadPicker();
    const html = rowsHtml(w.SessionRestartPicker.optionRows(LIVE_PREVIEW));
    const inputs = html.match(/<div role="option"[^>]*>/g) || [];
    assert.equal(inputs.length, 2, `expected 2 options, got ${inputs.length}`);
    for (const tag of inputs) {
        assert.ok(/aria-disabled="true"/.test(tag), `a live option is pickable: ${tag}`);
    }
    assert.ok(
        html.includes('data-kind="agent"'),
        'the wrapper option does not say it would start an agent',
    );
    assert.ok(
        html.includes('data-kind="shell"'),
        'the baseline projection (a plain shell) is not shown at all',
    );
    assert.ok(html.includes('data-now-kind="not_dead"'));
});

test('the baseline option leads and carries the projection', () => {
    const w = loadPicker();
    const html = rowsHtml(w.SessionRestartPicker.optionRows(LIVE_PREVIEW));
    const first = html.indexOf('data-choice-option=""');
    const second = html.indexOf('data-choice-option="claude-chrome"');
    assert.ok(first !== -1 && second !== -1, 'an option is missing entirely');
    assert.ok(first < second, 'the baseline option is not first');
    const baseline = html.slice(0, second);
    assert.ok(
        baseline.includes('>claude-chrome<'),
        'the baseline does not name the wrapper the session already records',
    );
    assert.ok(
        baseline.includes('launched with'),
        'the baseline is not tagged as what the session was launched with',
    );
    assert.ok(
        html.includes('>current<'),
        'the current wrapper is not marked',
    );
});

test('a dead pane makes the matching option pickable', () => {
    const w = loadPicker();
    const dead = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    dead.pane_state = 'dead';
    dead.unchanged = {
        kind: 'shell',
        detail: 'this pane was opened as a plain shell; restarting opens one again',
        actionable: true,
    };
    dead.options[0].actionable_now = true;
    dead.options[0].kind = 'agent';
    const html = rowsHtml(w.SessionRestartPicker.optionRows(dead));
    const inputs = html.match(/<div role="option"[^>]*>/g) || [];
    assert.equal(inputs.length, 2);
    for (const tag of inputs) {
        assert.ok(!/aria-disabled="true"/.test(tag), `a dead pane's option is locked: ${tag}`);
    }
});

test('an unreadable wrapper list is not an empty one', () => {
    const w = loadPicker();
    const unreadable = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    unreadable.options = [];
    unreadable.wrappers_status = 'unavailable';
    const empty = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    empty.options = [];
    empty.wrappers_status = 'ok';

    const a = w.SessionRestartPicker.wrapperNoticeHtml(unreadable);
    const b = w.SessionRestartPicker.wrapperNoticeHtml(empty);
    assert.notEqual(a, b, 'could-not-read renders identically to has-none');
    assert.ok(a.includes('launch profile list unreadable'), a);
    assert.ok(b.includes('no other launch profiles configured'), b);
});

test('a live or unreadable pane is named before the list', () => {
    const w = loadPicker();
    assert.ok(
        w.SessionRestartPicker.stateHtml(LIVE_PREVIEW, null).includes('>running<'),
        'a live session is not marked running',
    );
    const unknown = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    unknown.pane_state = 'unknown';
    const text = w.SessionRestartPicker.noticeHtml(unknown);
    assert.ok(
        text.includes('tmux did not answer'),
        'an unreadable pane reads as a healthy one',
    );
    const dead = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    dead.pane_state = 'dead';
    assert.ok(
        !w.SessionRestartPicker.stateHtml(dead, null).includes('running'),
        'a dead pane is marked as if it were live',
    );
    assert.ok(
        !w.SessionRestartPicker.noticeHtml(dead).includes('tmux did not answer'),
        'a dead pane is reported as unreadable',
    );
});

test('a hostile wrapper id and label stay plain strings in the picker rows', () => {
    const w = loadPicker();
    const hostile = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    hostile.options[0].agent_type = '"><img src=x onerror=alert(1)>';
    hostile.options[0].label = '<script>bad()</script>';
    const rows = w.SessionRestartPicker.optionRows(hostile);
    assert.equal(rows[1].value, hostile.options[0].agent_type);
    assert.equal(rows[1].label, '<script>bad()</script>');
    assert.ok(rows.every((r) => Object.keys(r).every((k) => !/html|svg/i.test(k))), 'a row carries markup');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

const GONE_SENTENCE = 'no transcript for claude session db81f6bf-85f9-448b'
    + '-a7f6-bc83f62659d9 exists under /Users/sam/.claude/projects, so '
    + 'it cannot be resumed';

function gonePreview() {
    const row = () => ({
        agent_type: 'w', label: 'a wrapper', is_current: false,
        resolvable: true, actionable_now: false, kind: 'transcript_missing',
        detail: GONE_SENTENCE, projected_kind: 'transcript_missing',
        projected_detail: GONE_SENTENCE, command: null, conversation: 'unknown',
    });
    const a = row();
    const b = row();
    b.agent_type = 'w2';
    b.label = 'another wrapper';
    return {
        name: 'row-dead', current_agent_type: 'claude', pane_state: 'dead',
        unchanged: {
            kind: 'transcript_missing', detail: GONE_SENTENCE,
            command: null, actionable: false,
        },
        projected: {
            kind: 'transcript_missing', detail: GONE_SENTENCE,
            command: null, actionable: false,
        },
        options: [a, b],
        wrappers_status: 'ok',
    };
}

test('a sentence every row shares is printed once, above the list', () => {
    const w = loadPicker();
    const preview = gonePreview();
    const rows = rowsHtml(w.SessionRestartPicker.optionRows(preview));
    const hoisted = w.SessionRestartPicker.sharedDetailHtml(preview);

    const inRows = rows.split(GONE_SENTENCE).length - 1;
    assert.equal(
        inRows, 0,
        `the shared sentence is still repeated ${inRows} times inside the rows`,
    );
    const above = hoisted.split(GONE_SENTENCE).length - 1;
    assert.equal(above, 1, 'the shared sentence is not stated once above');
    assert.ok(
        hoisted.includes('nothing here can resume it'),
        `the short sentence is missing: ${hoisted}`,
    );
    assert.ok(
        hoisted.includes('<details'),
        'the exact wording was dropped rather than folded away',
    );
});

test('a badge that reads the same on every row goes with the sentence', () => {
    const w = loadPicker();
    const preview = gonePreview();
    const rows = rowsHtml(w.SessionRestartPicker.optionRows(preview));
    assert.ok(
        !rows.includes('no transcript'),
        'the identical verdict tag is still repeated on every row',
    );
    assert.ok(rows.includes('a wrapper'), 'a row lost its title');
    assert.ok(rows.includes('another wrapper'), 'a row lost its title');
    assert.ok(
        rows.includes('aria-disabled="true"'),
        'a refused row stopped looking refused',
    );
    assert.ok(
        w.SessionRestartPicker.sharedDetailHtml(preview)
            .includes('conversation gone'),
        'the verdict was dropped from the rows without being stated above',
    );
});

test('rows that predict different rungs keep their badges', () => {
    const w = loadPicker();
    const preview = gonePreview();
    preview.options[1].projected_kind = 'shell';
    assert.equal(
        w.SessionRestartPicker.sharedDetail(preview).detail, '',
        'a differing rung was hoisted away on the strength of the wording',
    );
    const rows = rowsHtml(w.SessionRestartPicker.optionRows(preview));
    assert.ok(
        rows.includes('plain shell'),
        'the shell verdict was dropped from a row that alone predicts it',
    );
    assert.ok(
        rows.includes('no transcript'),
        'the other rows lost the verdict they still needed',
    );
});

test('a sentence that DIFFERS between rows stays on its own row', () => {
    const w = loadPicker();
    const preview = gonePreview();
    preview.pane_state = 'alive';
    preview.options[1].kind = 'agent';
    preview.options[1].projected_kind = 'agent';
    preview.options[1].actionable_now = true;
    preview.options[1].detail = 'starting another wrapper, resuming it';
    preview.options[1].projected_detail = 'starting another wrapper, resuming it';

    assert.equal(
        w.SessionRestartPicker.sharedDetail(preview).detail, '',
        'a sentence was hoisted out of rows that do not agree on it',
    );
    assert.equal(
        w.SessionRestartPicker.sharedDetailHtml(preview), '',
        'a statement was made above the list about rows that disagree',
    );
    const rows = rowsHtml(w.SessionRestartPicker.optionRows(preview));
    assert.ok(
        rows.includes(GONE_SENTENCE),
        'the refused row lost the only explanation it had',
    );
    assert.ok(
        rows.includes('starting another wrapper, resuming it'),
        'the actionable row lost its own sentence',
    );
});

test('a single-row panel keeps its detail rather than hoisting it', () => {
    const w = loadPicker();
    const preview = gonePreview();
    preview.options = [];
    assert.equal(
        w.SessionRestartPicker.sharedDetail(preview).detail, '',
        'the only row on the panel was stripped of its explanation',
    );
    assert.ok(
        rowsHtml(w.SessionRestartPicker.optionRows(preview)).includes(GONE_SENTENCE),
        'the baseline row lost its detail with nothing to share it with',
    );
});

test('GATE hoisting a sentence never enables a radio', () => {
    const w = loadPicker();
    const html = rowsHtml(w.SessionRestartPicker.optionRows(gonePreview()));
    const options = html.match(/<div role="option"[^>]*>/g) || [];
    assert.ok(options.length >= 3, `expected options, got ${options.length}`);
    for (const radio of options) {
        assert.ok(
            /aria-disabled="true"/.test(radio),
            `a refused row was painted pickable: ${radio}`,
        );
    }
});

test('the hoisted statement escapes what the server sent', () => {
    const w = loadPicker();
    const preview = gonePreview();
    const bad = '"><img src=x onerror=alert(1)>';
    preview.unchanged.detail = bad;
    preview.projected.detail = bad;
    preview.options.forEach((o) => {
        o.detail = bad;
        o.projected_detail = bad;
    });
    const html = w.SessionRestartPicker.sharedDetailHtml(preview);
    assert.ok(!html.includes('<img'), 'the hoisted sentence injected markup');
});

// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------

function streamPreview() {
    const opt = (id, label, current) => ({
        agent_type: id, label, is_current: current, resolvable: true,
        actionable_now: true, kind: 'agent',
        detail: `starting ${id}, which you picked, resuming the same conversation`,
        projected_kind: 'agent',
        projected_detail: `starting ${id}, which you picked, resuming the same conversation`,
    });
    return {
        name: 'row-dead', current_agent_type: 'claude', pane_state: 'dead',
        unchanged: {
            kind: 'agent', actionable: true,
            detail: 'restarting the agent this session was launched with, resuming the same conversation',
        },
        projected: {
            kind: 'agent', actionable: true,
            detail: 'restarting the agent this session was launched with, resuming the same conversation',
        },
        options: [opt('claude', 'claude', true), opt('cld', 'cld (subscription)', false),
            opt('cldor', 'cldor (openrouter)', false)],
        wrappers_status: 'ok',
    };
}

function visibleText(html) {
    return html
        .replace(/<span class="[^"]*cdd__sr[^"]*"[^>]*>[^<]*<\/span>/g, '')
        .replace(/<[^>]*>/g, ' ');
}

test('a row shows its name and tags, never the old prose', () => {
    const w = loadPicker();
    const html = rowsHtml(w.SessionRestartPicker.optionRows(streamPreview()));
    const seen = visibleText(html);
    for (const gone of ['would start the agent', 'which you picked',
        'resuming the same conversation', 'leave it on']) {
        assert.ok(!seen.includes(gone), `"${gone}" is still on screen`);
    }
    assert.ok(html.includes('>cld</span>'), 'the label was not split');
    assert.ok(html.includes('>subscription<'), html);
    assert.ok(html.includes('>current<'), 'the current wrapper is not tagged');
    assert.ok(!html.includes('plain shell') && !html.includes('new pane'), 'a shared agent rung was tagged');
});

test('the removed sentence survives as each row\'s accessible description', () => {
    const w = loadPicker();
    const html = rowsHtml(w.SessionRestartPicker.optionRows(streamPreview()));
    const inputs = html.match(/<div role="option"[^>]*>/g) || [];
    assert.equal(inputs.length, 4);
    for (const tag of inputs) {
        const id = (tag.match(/aria-describedby="([^"]+)"/) || [])[1];
        assert.ok(id, `a row lost its description: ${tag}`);
        assert.ok(html.includes(`id="${id}">`), `no element carries ${id}`);
    }
    assert.ok(html.includes('resuming the same conversation'),
        'the server sentence was deleted rather than kept for assistive tech');
});

test('a rung only some rows predict is tagged; one they all share is said once', () => {
    const w = loadPicker();
    const mixed = streamPreview();
    mixed.projected.kind = 'shell';
    mixed.unchanged.kind = 'shell';
    const html = rowsHtml(w.SessionRestartPicker.optionRows(mixed));
    assert.equal((html.match(/>plain shell</g) || []).length, 1,
        'exactly the shell row should carry a rung tag');
    assert.ok(html.includes('plain shell'));

    const recreate = streamPreview();
    recreate.projected.kind = 'recreate';
    recreate.options.forEach((o) => { o.projected_kind = 'recreate'; });
    assert.ok(!rowsHtml(w.SessionRestartPicker.optionRows(recreate)).includes('new pane'),
        'a tag every row shares is still repeated per row');
    assert.ok(w.SessionRestartPicker.stateHtml(recreate, null).includes('new pane'),
        'a tag every row shares was dropped without being said in the header');
});

test('an option with the same launch as the baseline folds into one row with both badges', () => {
    const w = loadPicker();
    const same = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    same.options[0].same_as_unchanged = true;
    const rows = w.SessionRestartPicker.optionRows(same);
    assert.equal(rows.length, 1, 'identical launches drew two rows');
    assert.equal(JSON.stringify(rows[0].tags), JSON.stringify(['launched with', 'current']));
    assert.equal(rows[0].value, '', 'the baseline lost its default selection');
    assert.equal(w.SessionRestartPicker.optionRows(LIVE_PREVIEW).length, 2);
});


test('the accounts fetch is fail-soft: no uuid, no API, an empty list or a failure draws no control', async () => {
    const w = loadPicker();
    const Options = w.SessionRestartOptions;
    assert.equal(await Options.accountsFor(null), null, 'a row with no durable key was asked');
    w.API = {};
    assert.equal(await Options.accountsFor('u1'), null, 'a missing route was called');
    w.API = { restartAccounts: async () => ({ options: [] }) };
    assert.equal(await Options.accountsFor('u1'), null, 'an empty list drew a control');
    w.API = { restartAccounts: async () => { throw new Error('boom'); } };
    assert.equal(await Options.accountsFor('u1'), null, 'a failed fetch broke the dialog');
    const answer = { options: [{ id: 'work', name: 'work' }], selected_id: 'work', pinned: true };
    w.API = { restartAccounts: async (uuid) => (uuid === 'u1' ? answer : null) };
    assert.equal(await Options.accountsFor('u1'), answer);
});

test('every row carries its family so a codex row can hide the account control', () => {
    const w = loadPicker();
    const preview = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    preview.options[0].family = 'codex';
    const rows = w.SessionRestartPicker.optionRows(preview);
    assert.equal(rows[1].data.family, 'codex');
    assert.equal(rows[0].data.family, '', 'the baseline row has no family of its own');
});

test('the launch choice mounts through the compiled bundle or not at all', () => {
    const w = loadPicker();
    const preview = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    assert.equal(w.SessionRestartOptions.mountChoice('slot', preview, null), null, 'a handle came from no bundle');
    const calls = [];
    const handle = { selected() {} };
    w.CloudeWeb = { mountLaunchChoice: (id, opts) => { calls.push([id, opts]); return handle; } };
    const answer = { options: [{ id: 'work', name: 'work' }], selected_id: 'work', pinned: true };
    assert.equal(w.SessionRestartOptions.mountChoice('slot', preview, answer), handle);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], 'slot');
    assert.equal(calls[0][1].accounts, answer, 'the accounts answer did not reach the control');
    assert.equal(calls[0][1].value, '', 'the dropdown does not start on the as-launched row');
    assert.equal(calls[0][1].rows[0].id, 'restart-choice-keep');
    assert.equal(w.SessionRestartOptions.mountChoice('slot', preview, undefined) && calls[1][1].accounts, null);
});

test('the account strings are the launch picker\'s, in Alex\'s words, and the old restart-only ones are gone', () => {
    assert.ok(!('session.restart.picker.account' in CATALOG));
    assert.ok(!('session.restart.picker.account.pin' in CATALOG));
    assert.equal(CATALOG['launch_picker.account.pin'], 'always launch this agent under this account');
    assert.equal(CATALOG['launch_picker.account.pin'], CATALOG['launch_picker.account.pin'].toLowerCase());
    assert.ok(!/sticky/i.test(CATALOG['launch_picker.account.pin']));
});

test('the as-launched row is the baseline the dropdown starts on', () => {
    const w = loadPicker();
    const rows = w.SessionRestartPicker.optionRows(LIVE_PREVIEW);
    assert.equal(rows[0].id, 'restart-choice-keep');
    assert.equal(rows[0].value, '');
    assert.ok(rows[0].tags.includes('launched with'), 'the baseline is not tagged launched with');
});

test('the baseline names its profile by the label the list uses, the id only when none is known', () => {
    const w = loadPicker();
    const preview = JSON.parse(JSON.stringify(LIVE_PREVIEW));
    preview.current_agent_type = 'swarm-upper';
    preview.options[0].agent_type = 'swarm-upper';
    preview.options[0].label = 'Swarm upper ranks';
    assert.equal(w.SessionRestartPicker.optionRows(preview)[0].label, 'Swarm upper ranks', 'the baseline showed the id');
    preview.options[0].label = '';
    assert.equal(w.SessionRestartPicker.optionRows(preview)[0].label, 'swarm-upper', 'no label did not fall back to the id');
});

const GONE_PREVIEW = {
    name: 'Cv-UI', current_agent_type: 'claude', pane_state: 'unknown',
    unchanged: { kind: 'cannot_determine', detail: 'x', actionable: false },
    projected: { kind: 'cannot_determine', detail: 'x', actionable: false },
    options: [
        { agent_type: 'claude', label: 'claude', is_current: true, kind: 'recreate', actionable_now: true },
        { agent_type: 'local', label: 'local', kind: 'cannot_determine', actionable_now: false },
    ],
};

test('a baseline that cannot start is not listed, nor is an option that cannot; the recorded wrapper starts checked (#2039)', () => {
    const w = loadPicker();
    const calls = [];
    w.CloudeWeb = { mountLaunchChoice: (id, opts) => { calls.push(opts); return {}; } };
    w.SessionRestartOptions.mountChoice('slot', JSON.parse(JSON.stringify(GONE_PREVIEW)), null);
    const rows = calls[0].rows;
    assert.equal(JSON.stringify(rows.map((r) => r.value)), '["claude"]', 'an unstartable row was listed');
    assert.ok(rows[0].tags.includes('launched with'));
    assert.equal(calls[0].value, 'claude');
});

test('any baseline that cannot start is not listed, not only cannot_determine (#2039)', () => {
    const w = loadPicker();
    const calls = [];
    w.CloudeWeb = { mountLaunchChoice: (id, opts) => { calls.push(opts); return {}; } };
    const p = JSON.parse(JSON.stringify(GONE_PREVIEW));
    p.unchanged = { kind: 'transcript_missing', detail: 'x', actionable: false };
    p.projected = { kind: 'transcript_missing', detail: 'x', actionable: false };
    w.SessionRestartOptions.mountChoice('slot', p, null);
    assert.equal(JSON.stringify(calls[0].rows.map((r) => r.value)), '["claude"]');
    assert.equal(calls[0].value, 'claude');
});

test('nothing is preselected when the recorded wrapper cannot start (#2039)', () => {
    const w = loadPicker();
    const calls = [];
    w.CloudeWeb = { mountLaunchChoice: (id, opts) => { calls.push(opts); return {}; } };
    const p = JSON.parse(JSON.stringify(GONE_PREVIEW));
    p.options[0].actionable_now = false;
    p.options.push({ agent_type: 'cld', label: 'cld', kind: 'recreate', actionable_now: true });
    w.SessionRestartOptions.mountChoice('slot', p, null);
    assert.equal(JSON.stringify(calls[0].rows.map((r) => r.value)), '["cld"]');
    assert.equal(calls[0].value, '__none__', 'a row was preselected');
});

await runQueue();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
