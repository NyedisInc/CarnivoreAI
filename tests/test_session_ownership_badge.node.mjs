
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
// SLICE 3: the session data layer lives in the compiled bundle, and the
// `Launchpad` fields this harness drives are accessors over that one
// store. The REAL client/dist/app.js is evaluated in this sandbox rather
// than stubbed, so these assertions run against the shipped path.
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => (void|Promise<void>)} fn  Body; throwing marks it failed.
 * @returns {Promise<void>}
 */
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

/**
 * Read one file from the repo root.
 * @param {...string} parts  Path segments below the repo root.
 * @returns {string} File contents.
 */
function read(...parts) {
    return fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
}

function makeContext({ attachable, live }) {
    const fakeDocument = {
        getElementById() { return null; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
        createElement() {
            return {
                addEventListener() {},
                classList: { add() {}, remove() {}, toggle() {} },
                style: {},
                dataset: {},
                set textContent(_v) {},
                get textContent() { return ''; },
                innerHTML: '',
            };
        },
    };
    const fakeWindow = {
        API: {
            async listAttachableSessions() { return attachable.map((r) => ({ ...r })); },
            async listSessions() { return live.map((r) => ({ ...r })); },
            async getCurrentSession() { return null; },
        },
        localStorage: {
            getItem() { return null; },
            setItem() {},
            removeItem() {},
        },
        addEventListener() {},
        removeEventListener() {},
        dispatchEvent() {},
        CustomEvent: function CustomEvent(type, opts) {
            this.type = type;
            this.detail = opts && opts.detail;
        },
        requestAnimationFrame(cb) { cb(); },
        matchMedia() { return { matches: false, addEventListener() {} }; },
    };
    fakeWindow.window = fakeWindow;
    const context = {
        window: fakeWindow,
        document: fakeDocument,
        console: { log() {}, warn() {}, error() {}, debug() {} },
        localStorage: fakeWindow.localStorage,
        requestAnimationFrame: fakeWindow.requestAnimationFrame,
        CustomEvent: fakeWindow.CustomEvent,
        setInterval() { return 0; },
        clearInterval() {},
        setTimeout() { return 0; },
        clearTimeout() {},
        alert() {},
    };
    vm.createContext(context);
    installCloudeWeb(context);
    return { context, fakeWindow };
}


async function mergeLaunchpad(payloads) {
    const { context } = makeContext(payloads);
    const store = context.window.CloudeWeb.launchpad.sessions;
    await store.loadRunningSessions((key) => key);
    return store.runningSessions;
}

async function mergeSidebar(payloads) {
    const { context } = makeContext(payloads);
    const sb = context.window.SessionSidebar;
    sb.repaint = () => {};
    await sb._fetchAndRender();
    return sb._rows;
}

const MERGES = [['the home screen', mergeLaunchpad], ['the drawer', mergeSidebar]];

function row(rows, name) {
    const found = rows.find((r) => r.name === name);
    assert.ok(found, `no merged row for ${name}: ${JSON.stringify(rows)}`);
    return found;
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

for (const [label, merge] of MERGES) {
    await test(`${label}: an open session the app CREATED badges owned`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'cloude_ses_abc',
                activity_status: 'idle',
                created_by_cloude: true,
                session: { id: 'ses_abc' },
            }],
        });
        assert.equal(row(rows, 'cloude_ses_abc').created_by_cloude, true);
    });

    await test(`${label}: an open session the app ADOPTED badges external`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'handmade',
                activity_status: 'idle',
                created_by_cloude: false,
                session: { id: 'adopted:handmade' },
            }],
        });
        assert.equal(row(rows, 'handmade').created_by_cloude, false);
    });

    // -----------------------------------------------------------------
    // -----------------------------------------------------------------

    await test(`${label}: an owned session wearing an adopted: id stays owned`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'cloude_ses_ec5bf2a3',
                activity_status: 'idle',
                created_by_cloude: true,
                session: { id: 'adopted:cloude_ses_ec5bf2a3' },
            }],
        });
        assert.equal(row(rows, 'cloude_ses_ec5bf2a3').created_by_cloude, true,
            'an `adopted:` id prefix is not evidence of adoption - it is what '
            + 'a restart-time re-attach mints for a session we still own');
    });

    await test(`${label}: an external session with a plain id stays external`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'not_ours',
                activity_status: 'idle',
                created_by_cloude: false,
                session: { id: 'some-plain-id' },
            }],
        });
        assert.equal(row(rows, 'not_ours').created_by_cloude, false);
    });

    // -----------------------------------------------------------------
    // -----------------------------------------------------------------

    await test(`${label}: created_by_us wins over created_by_cloude when both are on the wire`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'cloude_ses_new_field',
                activity_status: 'idle',
                created_by_cloude: false,
                created_by_us: true,
                session: { id: 'ses_new_field' },
            }],
        });
        assert.equal(row(rows, 'cloude_ses_new_field').created_by_cloude, true,
            'created_by_us must win when the two disagree');
    });

    await test(`${label}: created_by_cloude alone still works when created_by_us is absent`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'cloude_ses_legacy_only',
                activity_status: 'idle',
                created_by_cloude: true,
                session: { id: 'ses_legacy_only' },
            }],
        });
        assert.equal(row(rows, 'cloude_ses_legacy_only').created_by_cloude, true);
    });

    // -----------------------------------------------------------------
    // -----------------------------------------------------------------

    await test(`${label}: opening/closing an adopted session never flips it`, async () => {
        const closed = await merge({
            attachable: [{
                name: 'handmade',
                created_by_cloude: false,
                created_at_epoch: 100,
                window_count: 1,
            }],
            live: [],
        });
        const open = await merge({
            attachable: [],
            live: [{
                tmux_session: 'handmade',
                activity_status: 'idle',
                created_by_cloude: false,
                session: { id: 'adopted:handmade' },
            }],
        });
        assert.equal(row(closed, 'handmade').created_by_cloude, false);
        assert.equal(row(open, 'handmade').created_by_cloude,
            row(closed, 'handmade').created_by_cloude);
    });

    await test(`${label}: opening/closing an owned session never flips it`, async () => {
        const closed = await merge({
            attachable: [{
                name: 'cloude_ses_abc',
                created_by_cloude: true,
                created_at_epoch: 100,
                window_count: 1,
            }],
            live: [],
        });
        const open = await merge({
            attachable: [],
            live: [{
                tmux_session: 'cloude_ses_abc',
                activity_status: 'idle',
                created_by_cloude: true,
                session: { id: 'adopted:cloude_ses_abc' },
            }],
        });
        assert.equal(row(closed, 'cloude_ses_abc').created_by_cloude, true);
        assert.equal(row(open, 'cloude_ses_abc').created_by_cloude,
            row(closed, 'cloude_ses_abc').created_by_cloude);
    });

    // -----------------------------------------------------------------
    // -----------------------------------------------------------------

    await test(`${label}: a live row that omits the flag is not claimed as owned`, async () => {
        const rows = await merge({
            attachable: [],
            live: [{
                tmux_session: 'cloude_mystery',
                activity_status: 'idle',
                session: { id: 'ses_mystery' },
            }],
        });
        assert.equal(row(rows, 'cloude_mystery').created_by_cloude, false);
    });
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const manager = read('src', 'core', 'session_manager.py');
const backend = read('src', 'core', 'tmux_backend.py');
const resolver = read('src', 'core', 'tmux_listing_parse.py');

await test('the server answers ownership from the persisted owned set', () => {
    assert.match(resolver, /return name in owned_names/,
        '/sessions/attachable must keep sourcing the flag from the owned set');
    assert.match(backend, /created_by_cloude = resolve_ownership\(/,
        'the backend must delegate to the shared resolver, not grow a '
        + 'second copy of the ownership decision');
    assert.doesNotMatch(backend, /created_by_cloude = name in owned_names/,
        'the backend kept an inline copy of the owned-name tier; that is '
        + 'how the badge came to disagree with itself before');
    assert.match(manager, /created_by_cloude=bool\(\s*tmux_session_name/,
        'SessionInfo must carry the same flag from the same set, or the '
        + 'client has nothing to read on the merge path and will invent one');
});

await test('adoption still does not claim ownership', () => {
    assert.match(manager,
        /The adopted session is NOT added to ``owned_tmux_sessions``/,
        'adopt_external_session must still leave the owned set alone');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

await test('both surfaces render the same flag as the same badge', () => {
    // the legacy twin
    const meta = read('web', 'src', 'lib', 'sidebar-shell', 'row-text.ts');
    assert.match(meta, /if \(own == null\)/,
        'the unmeasured origin is its own branch, not folded into external');
    assert.match(meta, /text: 'unknown'/, 'and it says so');
    assert.match(meta, /if \(own === true\)/);
    assert.match(meta, /text: 'tmux'/);
    assert.match(meta, /text: 'external'/);
    assert.ok(!meta.includes("created_by_cloude ? 'tmux' : 'external'"),
        'the old two-way ternary must not come back');
    const catalog = read('client', 'js', 'i18n', 'catalog.en.js');
    assert.match(catalog, /'session\.badge\.tmux': 'tmux'/);
    assert.match(catalog, /'session\.badge\.external': 'external'/);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
