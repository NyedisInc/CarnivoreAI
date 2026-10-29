// timeline was destroyed by the act of reading it.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
// SLICE 3: the session data layer lives in the compiled bundle, and the
// `Launchpad` fields this harness drives are accessors over that one
// store. The REAL client/dist/app.js is evaluated in this sandbox rather
// than stubbed, so these assertions run against the shipped path.
import { installCloudeWeb, unrefTimer } from './helpers/cloude-web-sandbox.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

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

function loadModules(names) {
    function makeDiv() {
        let text = '';
        return {
            set textContent(v) { text = v == null ? '' : String(v); },
            get textContent() { return text; },
            get innerHTML() {
                return text
                    .replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;');
            },
        };
    }
    const context = {
        console: { log() {}, warn() {}, error() {} },
        document: { createElement: () => makeDiv() },
        Date, JSON, Math, Set, Map, Array, Object, String, Number, Boolean,
        Promise, setTimeout: unrefTimer(setTimeout), clearTimeout, RegExp,
    };
    context.window = context;
    vm.createContext(context);
    installCloudeWeb(context);
    for (const name of names) {
        vm.runInContext(
            fs.readFileSync(path.join(ROOT, 'client', 'js', name), 'utf8'),
            context,
            { filename: name },
        );
    }
    return context;
}

const win = loadModules([
    'session-status-ui.js',
    'session-row-actions.js',
]);
const Fetch = win.SessionSidebarFetch;

function rows() {
    return [
        { name: 'old_work', created_at_epoch: 300, last_work_at: '2026-09-01T10:00:00Z' },
        { name: 'new_work', created_at_epoch: 100, last_work_at: '2026-09-03T10:00:00Z' },
        { name: 'never_worked', created_at_epoch: 200, last_work_at: null },
    ];
}

const names = (list) => list.map((r) => r.name);

await test('the order is by WORK, newest first', () => {
    assert.deepEqual(
        names(Fetch.defaultSort(rows())),
        ['new_work', 'old_work', 'never_worked'],
        'a session worked more recently must come first, regardless of age',
    );
});

await test('SELECTING a row does not move it - the core assertion', () => {
    const before = names(Fetch.defaultSort(rows()));
    const clicked = rows().map(
        (r) => (r.name === 'never_worked' ? { ...r, is_this_tab: true, is_active: true } : r),
    );
    assert.deepEqual(names(Fetch.defaultSort(clicked)), before,
        'clicking a row reordered the list - this is the regression');
    const clickedMid = rows().map(
        (r) => (r.name === 'old_work' ? { ...r, is_this_tab: true, is_active: true } : r),
    );
    assert.deepEqual(names(Fetch.defaultSort(clickedMid)), before);
});

await test('NEITHER is_this_tab NOR is_active appears in the sort at all', () => {
    const src = fs.readFileSync(
        path.join(ROOT, 'web', 'src', 'lib', 'drawer', 'fetch.ts'), 'utf8');
    const body = src.slice(src.indexOf('function defaultSort'));
    const sortBody = body.slice(0, body.indexOf('\n}'));
    assert.ok(sortBody.includes('last_work_at'), 'the sort was not found where this reads it');
    assert.ok(!sortBody.includes('is_this_tab'),
        'is_this_tab is back in defaultSort - a click can reorder the list again');
    assert.ok(!sortBody.includes('is_active'),
        'is_active is back in defaultSort - attaching can reorder the list again');
});

await test('UNRECORDED is a third outcome: last, but never treated as epoch 0', () => {
    const onlyUnworked = [
        { name: 'b', created_at_epoch: 100, last_work_at: null },
        { name: 'a', created_at_epoch: 200, last_work_at: null },
    ];
    assert.deepEqual(names(Fetch.defaultSort(onlyUnworked)), ['a', 'b'],
        'with nothing measured, rows keep a stable newest-created-first order');
    const ancientWork = [
        { name: 'never', created_at_epoch: 999, last_work_at: null },
        { name: 'ancient', created_at_epoch: 1, last_work_at: '1970-01-01T00:00:01Z' },
    ];
    assert.deepEqual(names(Fetch.defaultSort(ancientWork)), ['ancient', 'never']);
});

await test('an unrecorded row SAYS so, so last does not read as stalest', () => {
    assert.ok(Fetch.workAttr({ last_work_at: null }).includes('data-work="unrecorded"'));
    const css = fs.readFileSync(path.join(ROOT, 'client', 'css', 'session-sidebar-rows.css'), 'utf8');
    assert.ok(css.includes('.session-sidebar-row[data-work="unrecorded"] .session-sidebar-row-name'),
        'a machine-readable attribute alone is not visible to a person');
    assert.ok(Fetch.workAttr({ last_work_at: '2026-09-03T10:00:00Z' })
        .includes('data-work="recorded"'));
});


await test('the stamp index takes the MAX per tmux name, not the last seen', () => {
    const index = Fetch.workStampIndex([
        { tmux_name: 'cloude_Mac', last_work_at: '2026-09-03T12:00:00Z' },
        { tmux_name: 'cloude_Mac', last_work_at: '2026-08-01T12:00:00Z' },
        { tmux_name: 'cloude_Other', last_work_at: null },
        { tmux_name: null, last_work_at: '2026-09-03T12:00:00Z' },
    ]);
    assert.equal(index.get('cloude_Mac'), '2026-09-03T12:00:00Z');
    assert.equal(index.has('cloude_Other'), false,
        'a row with no stamp must contribute NOTHING, not a zero');
    assert.equal(index.size, 1);
});

await test('the launcher orders its own lists the same way', async () => {
    const rows = [
        { name: 'cloude_stale', created_by_cloude: true, created_at_epoch: 9000 },
        { name: 'cloude_busy', created_by_cloude: true, created_at_epoch: 1000 },
        { name: 'cloude_none', created_by_cloude: true, created_at_epoch: 5000 },
    ];
    const records = [
        { tmux_name: 'cloude_stale', tmux_created_epoch: 9000, last_work_at: '2026-09-01T00:00:00Z' },
        { tmux_name: 'cloude_busy', tmux_created_epoch: 1000, last_work_at: '2026-09-09T00:00:00Z' },
    ];
    const stamps = Fetch.workStampIndex(records);
    const expected = ['cloude_busy', 'cloude_stale', 'cloude_none'];

    const sidebarRows = rows.map((r) => ({
        ...r,
        last_work_at: stamps.get(r.name) || null,
    }));
    assert.deepEqual(
        [...Fetch.defaultSort(sidebarRows)].map((r) => r.name),
        expected,
        'the sidebar stopped ordering by work'
    );

    const web = installCloudeWeb(vm.createContext({
        console: { log() {}, warn() {}, error() {} },
    }));
    const store = web.launchpad.sessions;
    store.useHost({
        listAttachableSessions: async () => rows.map((r) => ({ ...r, status: 'idle' })),
        listSessions: async () => [{
            tmux_session: 'cloude_none', activity_status: 'idle', session: { id: 'ses_x' },
        }],
        getCurrentSession: async () => null,
        listSessionRecords: async () => records,
    });
    await store.loadRunningSessions((k) => k);
    assert.deepEqual(
        [...store.runningSessions].map((r) => r.name),
        expected,
        'the launcher disagrees with the sidebar, or leads with is_active again'
    );
    assert.equal(store.runningSessions.find((r) => r.name === 'cloude_none').is_active, true,
        'the row that must not move was not actually the live one');
    store.reset();
    store.useHost(null);

    const src = fs.readFileSync(
        path.join(ROOT, 'web', 'src', 'lib', 'sidebar-shell', 'row-text.ts'), 'utf8');
    assert.ok(/'data-work':\s*'unrecorded'/.test(src),
        'the drawer no longer labels its unrecorded rows');
    assert.ok(/'data-work':\s*'recorded'/.test(src),
        'the drawer no longer labels its recorded rows');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
