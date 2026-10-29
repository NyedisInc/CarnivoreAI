
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE = path.join(__dirname, '..', 'client', 'js', 'session-sidebar-heading-actions.js');

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

function row(o) {
    return { kind: 'agent', asleep: false, session_id: null, ...o };
}

const ROWS = [
    row({ name: 'c_a', session_uuid: 'ua', session_id: 'ses_a', project_id: 3, project_name: 'Api' }),
    row({ name: 'c_b', session_uuid: 'ub', project_id: 3, project_name: 'Api' }),
    row({ name: 'c_z', session_uuid: 'uz', project_id: 3, project_name: 'Api', asleep: true }),
    row({ name: 'c_web', session_uuid: 'uw', project_id: 3, project_name: 'Api', kind: 'browser' }),
    row({ name: 'c_other', session_uuid: 'uo', session_id: 'ses_o', project_id: 4, project_name: 'Web' }),
];

function standUp(opts = {}) {
    const calls = [];
    const spoken = [];
    const reported = [];
    const modal = [];
    const sandbox = { console: { log() {}, warn() {}, error() {} } };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.document = { addEventListener() {} };
    sandbox.CloudeI18n = { t: (key, p) => `${key}${p ? JSON.stringify(p) : ''}` };
    sandbox.SessionSidebar = {
        _rows: ROWS.map((r) => ({ ...r })),
        _fetchAndRender: async () => { calls.push(['refresh']); },
    };
    sandbox.SessionSidebarKindGroups = {
        isAgentKind: (r) => r.kind === 'agent',
        isBrowser: (r) => r.kind === 'browser',
    };
    const groupOf = opts.groupOf || {};
    sandbox.SessionSidebarGroupStore = {
        isUsable: () => true,
        projectBandKeyFor: (id) => `p:${id}`,
        groupOf: (name) => groupOf[name] || null,
        groupByUuid: (u) => ({ group_uuid: u, name: 'focus' }),
    };
    sandbox.SessionSidebarGroupActions = { announce: (t) => spoken.push(t) };
    sandbox.WriteFailureNotice = { report: (t) => reported.push(t) };
    sandbox.SessionRowMenuSleep = { releaseThisTab: (ctx) => calls.push(['release', ctx.name]) };
    sandbox.App = {
        showConfirmModal: async (...args) => { modal.push(args); return opts.confirm !== false; },
    };
    const reject = (name) => { if (opts.failClose === name) throw new Error('tmux said no'); };
    sandbox.API = {
        destroySession: async (id) => { calls.push(['destroySession', id]); reject(id === 'ses_a' ? 'c_a' : id); },
        destroyExternalSession: async (name) => { calls.push(['destroyExternal', name]); reject(name); },
        deleteSessionRecord: async (uuid) => { calls.push(['deleteRecord', uuid]); },
        archiveProject: async (name) => { calls.push(['archive', name]); return { archived_at: 'now' }; },
        sleepSession: async (uuid) => {
            calls.push(['sleep', uuid]);
            return opts.sleepRefuse === uuid
                ? { status: 'refused', detail: 'no conversation id' } : { status: 'asleep' };
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(MODULE, 'utf8'), sandbox, { filename: MODULE });
    return { H: sandbox.SessionSidebarHeadingActions, calls, spoken, reported, modal };
}

const writes = (calls) => calls.filter((c) => c[0] !== 'refresh' && c[0] !== 'release');

await test('a project heading files the same rows its section draws', () => {
    const { H } = standUp();
    assert.deepEqual(H.projectRows('p:3').map((r) => r.name), ['c_a', 'c_b', 'c_z'],
        'agent rows of project 3 only: no browser row, no row of another project');
});

await test('cancelling remove sends nothing', async () => {
    const { H, calls, modal } = standUp({ confirm: false });
    assert.equal(await H.removeProject('p:3'), false);
    assert.equal(modal.length, 1, 'the in-app modal asked');
    assert.equal(modal[0][5], 'danger', 'the confirming button is the danger variant');
    assert.deepEqual(writes(calls), [], 'no close, no archive');
});

await test('confirmed remove closes every session by its own route, then archives', async () => {
    const { H, calls, reported, modal } = standUp();
    assert.equal(await H.removeProject('p:3'), true);
    assert.ok(modal[0][2].includes('"count":3'), 'the modal names the real session count');
    assert.deepEqual(writes(calls), [
        ['destroySession', 'ses_a'],
        ['destroyExternal', 'c_b'],
        ['deleteRecord', 'uz'],
        ['archive', 'Api'],
    ], 'closes first, archive last, never a hard delete; project 4 untouched');
    assert.deepEqual(reported, []);
});

await test('one failed close keeps the project and says which session', async () => {
    const { H, calls, reported } = standUp({ failClose: 'c_b' });
    assert.equal(await H.removeProject('p:3'), false);
    assert.ok(!calls.some((c) => c[0] === 'archive'), 'no archive over a session still running');
    assert.equal(reported.length, 1);
    assert.ok(reported[0].includes('c_b: tmux said no'), reported[0]);
});

await test('sleep on a project sleeps awake non-browser rows only', async () => {
    const { H, calls, reported } = standUp();
    const res = await H.sleepProject('p:3');
    assert.deepEqual(writes(calls), [['sleep', 'ua'], ['sleep', 'ub']],
        'the asleep row and the browser row are skipped, project 4 untouched');
    assert.deepEqual({ ...res }, { slept: 2, failed: 0 });
    assert.deepEqual(reported, []);
});

await test('sleep on a group sleeps its members and reports a refusal', async () => {
    const { H, calls, reported } = standUp({
        groupOf: { c_a: 'g1', c_other: 'g1', c_b: 'g2' }, sleepRefuse: 'uo',
    });
    const res = await H.sleepGroup('g1');
    assert.deepEqual(writes(calls), [['sleep', 'ua'], ['sleep', 'uo']]);
    assert.deepEqual({ ...res }, { slept: 1, failed: 1 });
    assert.equal(reported.length, 1);
    assert.ok(reported[0].includes('no conversation id'), reported[0]);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures || passes === 0) process.exit(1);
