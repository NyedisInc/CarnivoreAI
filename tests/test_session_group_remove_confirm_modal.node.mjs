
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');
const GROUP_ACTIONS = path.join(repoRoot, 'client', 'js', 'session-sidebar-group-actions.js');

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

function fillTemplate(template, params) {
    const p = params || {};
    let form = template;
    if (template && typeof template === 'object') {
        const n = Number(p.count);
        form = (n === 1 ? template.one : template.other) || template.other;
    }
    return String(form).replace(/\{(\w+)\}/g, (whole, key) => (
        Object.prototype.hasOwnProperty.call(p, key) ? String(p[key]) : whole
    ));
}

const CATALOG = {
    'sidebar.group.remove.title': 'remove group',
    'sidebar.group.remove.message': 'remove the group "{name}"?',
    'sidebar.group.remove.detail': {
        one: '{count} agent moves to its own project, or rogue agents if '
            + 'it has none. no agent is removed.',
        other: '{count} agents move to their own project, or rogue agents '
            + 'if none. no agent is removed.',
    },
    'sidebar.group.remove.confirm': 'remove',
    'sidebar.group.remove.cancel': 'cancel',
};

function standUp(opts = {}) {
    const confirmAnswer = opts.confirmAnswer !== false;
    const deleteFails = !!opts.deleteFails;

    const modalCalls = [];
    const nativeConfirmCalls = [];
    const apiCalls = [];
    const spoken = [];
    const failuresReported = [];
    let repaintCount = 0;
    let applied = null;

    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;

    sandbox.confirm = (...args) => {
        nativeConfirmCalls.push(args);
        throw new Error('window.confirm must never be called (issue #648)');
    };

    sandbox.CloudeI18n = {
        t(key, params) {
            const entry = Object.prototype.hasOwnProperty.call(CATALOG, key)
                ? CATALOG[key] : key;
            return fillTemplate(entry, params);
        },
    };

    sandbox.App = {
        showConfirmModal(title, message, details, primaryLabel, secondaryLabel) {
            modalCalls.push({ title, message, details, primaryLabel, secondaryLabel });
            return Promise.resolve(confirmAnswer);
        },
    };

    const GROUP = {
        group_uuid: 'g-orchard',
        name: 'Orchard',
        members: ['cloude_a', 'cloude_b'],
    };

    sandbox.SessionSidebarGroupStore = {
        isUsable: () => true,
        groupByUuid: (uuid) => (uuid === GROUP.group_uuid ? GROUP : null),
        groupOf: () => null,
        bandKeyFor: (uuid) => `g:${uuid}`,
        labelFor: () => GROUP.name,
        apply(body) { applied = body; },
    };
    sandbox.SessionSidebar = { repaint() { repaintCount += 1; } };
    sandbox.SessionSidebarReorder = { announce: (text) => spoken.push(String(text)) };
    sandbox.WriteFailureNotice = { report: (text) => failuresReported.push(String(text)) };

    sandbox.API = {
        deleteSessionGroup: async (groupUuid) => {
            apiCalls.push(['delete', groupUuid]);
            if (deleteFails) throw new Error('503 datastore unavailable');
            return { status: 'ok', groups: [], freed: GROUP.members.length };
        },
    };

    const ctx = vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(GROUP_ACTIONS, 'utf8'), ctx, { filename: GROUP_ACTIONS });

    return {
        api: sandbox.SessionSidebarGroupActions,
        group: GROUP,
        modalCalls,
        nativeConfirmCalls,
        apiCalls,
        spoken,
        failuresReported,
        getRepaintCount: () => repaintCount,
        getApplied: () => applied,
    };
}


await test('removing a group never calls window.confirm', async () => {
    const env = standUp({ confirmAnswer: true });
    await env.api.deleteGroup(env.group.group_uuid);
    assert.deepEqual(env.nativeConfirmCalls, [], 'window.confirm was invoked');
});

await test('the app\'s own modal is asked, naming the real group and the real destination', async () => {
    const env = standUp({ confirmAnswer: true });
    await env.api.deleteGroup(env.group.group_uuid);

    assert.equal(env.modalCalls.length, 1, 'showConfirmModal was not called exactly once');
    const call = env.modalCalls[0];
    assert.equal(call.title, 'remove group');
    assert.equal(call.message, 'remove the group "Orchard"?');
    assert.match(call.details, /own project/, 'detail does not name the real destination');
    assert.match(call.details, /rogue agents/, 'detail drops the rogue-agents case');
    assert.doesNotMatch(call.details, /\bother\b/, 'the retired "other" band leaked back into the copy');
    assert.equal(call.primaryLabel, 'remove');
    assert.equal(call.secondaryLabel, 'cancel');
});

await test('CANCEL (the modal resolves false) keeps the group: no delete, no repaint, no announcement', async () => {
    const env = standUp({ confirmAnswer: false });
    await env.api.deleteGroup(env.group.group_uuid);

    assert.deepEqual(env.apiCalls, [], 'a cancelled removal still deleted the group');
    assert.equal(env.getApplied(), null, 'a cancelled removal still applied a response');
    assert.equal(env.getRepaintCount(), 0, 'a cancelled removal still repainted');
    assert.equal(env.spoken.length, 0, 'a cancelled removal still announced something');
});

await test('CONFIRM (the modal resolves true) removes the group: one delete, applied, announced', async () => {
    const env = standUp({ confirmAnswer: true });
    await env.api.deleteGroup(env.group.group_uuid);

    assert.deepEqual(env.apiCalls, [['delete', 'g-orchard']], 'the delete write was not sent, or sent wrong');
    assert.ok(env.getApplied(), 'the response was never applied to the group store');
    assert.equal(env.getRepaintCount(), 1, 'the sidebar was not told to repaint');
    assert.equal(env.spoken.length, 1, 'the removal was not announced');
    assert.match(env.spoken[0], /project or rogue agents/, 'the announcement still claims "other"');
    assert.doesNotMatch(env.spoken[0], /\bother\b/, 'the retired "other" band leaked into the announcement');
});

await test('NEGATIVE CONTROL: the two branches actually differ', async () => {
    const cancelled = standUp({ confirmAnswer: false });
    await cancelled.api.deleteGroup(cancelled.group.group_uuid);
    const confirmed = standUp({ confirmAnswer: true });
    await confirmed.api.deleteGroup(confirmed.group.group_uuid);

    assert.notEqual(cancelled.apiCalls.length, confirmed.apiCalls.length,
        'cancel and confirm sent the same number of delete requests');
});

await test('a refused delete announces failure through both surfaces, not success', async () => {
    const env = standUp({ confirmAnswer: true, deleteFails: true });
    await env.api.deleteGroup(env.group.group_uuid);

    assert.deepEqual(env.apiCalls, [['delete', 'g-orchard']]);
    assert.equal(env.spoken.length, 1);
    assert.match(env.spoken[0], /could not remove/);
    assert.equal(env.failuresReported.length, 1, 'the failure never reached the visible surface');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.log('FAILURES PRESENT');
    process.exit(1);
}
console.log('ALL PASS');
