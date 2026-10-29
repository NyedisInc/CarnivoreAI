
import { strict as assert } from 'node:assert';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import fs from 'node:fs';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(here, '..', 'client', 'js', 'preferences.js');

function makeApi(responses) {
    const queue = responses.slice();
    const sent = [];
    return {
        sent,
        async call(endpoint, options = {}) {
            sent.push({ endpoint, options });
            const next = queue.shift();
            if (next instanceof Error) throw next;
            if (next === undefined) {
                throw new Error(`no queued response for ${endpoint}`);
            }
            return next;
        },
    };
}

function staleError(revision, values) {
    const err = new Error('HTTP 409');
    err.status = 409;
    err.detail = { status: 'stale_revision', revision, values };
    return err;
}

function loadModule() {
    delete require.cache[require.resolve(MODULE_PATH)];
    delete globalThis.Preferences;
    const mod = require(MODULE_PATH);
    mod.reset();
    return mod;
}

const block = (revision, values) => ({
    status: 'unchanged', schema_version: 1, revision, values,
});


test('applying a received change generates no outgoing save', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, { theme: 'claude' })]);
    await prefs.hydrate(api);

    prefs.subscribe((name, value) => { prefs.set(name, value, api); });

    const applied = prefs.applyRemote({
        type: 'preferences.changed',
        revision: 2,
        changed: { theme: 'matrix' },
        origin_client_id: 'some-other-browser',
    });

    assert.equal(applied, true);
    assert.equal(prefs.get('theme'), 'matrix');
    assert.equal(api.sent.length, 1,
        'a received change produced an outgoing request; two clients would echo forever');
    assert.equal(api.sent[0].options.method, undefined, 'the only request was the hydrate GET');
});

test('a browser ignores the event raised by its own write', async () => {
    const prefs = loadModule();
    const api = makeApi([block(0, {})]);
    await prefs.hydrate(api);

    const applied = prefs.applyRemote({
        revision: 9,
        changed: { theme: 'matrix' },
        origin_client_id: prefs.clientId,
    });

    assert.equal(applied, false);
    assert.equal(prefs.revision(), 0);
});


test('with the read failing, no write is ever sent', async () => {
    const prefs = loadModule();
    const api = makeApi([new Error('network down')]);

    const status = await prefs.hydrate(api);
    assert.equal(status, prefs.READ_FAILED);

    const result = await prefs.set('theme', 'matrix', api);

    assert.equal(result.status, 'refused');
    assert.equal(api.sent.length, 1,
        'a failed read was followed by a write; that saves a default over a real setting');
});

test('a write before hydration has run at all is refused', async () => {
    const prefs = loadModule();
    const api = makeApi([]);

    const result = await prefs.set('theme', 'matrix', api);

    assert.equal(result.status, 'refused');
    assert.equal(api.sent.length, 0);
});

test('a failed read reports no value, so a control keeps its own default', async () => {
    const prefs = loadModule();
    const api = makeApi([new Error('network down')]);
    await prefs.hydrate(api);

    assert.equal(prefs.get('sidebar_density', 'cozy'), 'cozy');
    assert.equal(prefs.get('theme'), undefined);
});


test('the same event twice applies once', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, {})]);
    await prefs.hydrate(api);

    const frame = { revision: 2, changed: { theme: 'matrix' } };
    assert.equal(prefs.applyRemote(frame), true);
    assert.equal(prefs.applyRemote(frame), false, 'a duplicate frame was applied twice');
    assert.equal(prefs.revision(), 2);
});

test('an out of order event is ignored rather than reverting a newer one', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, {})]);
    await prefs.hydrate(api);

    prefs.applyRemote({ revision: 3, changed: { theme: 'matrix' } });
    const older = prefs.applyRemote({ revision: 2, changed: { theme: 'claude' } });

    assert.equal(older, false);
    assert.equal(prefs.get('theme'), 'matrix', 'a reordered frame reverted a newer value');
    assert.equal(prefs.revision(), 3);
});

test('a dropped event is closed by the next higher one', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, {})]);
    await prefs.hydrate(api);

    prefs.applyRemote({ revision: 3, changed: { sidebar_density: 'compact' } });

    assert.equal(prefs.get('sidebar_density'), 'compact');
    assert.equal(prefs.revision(), 3);
});

test('a null in a received change unsets the field', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, { theme: 'matrix' })]);
    await prefs.hydrate(api);

    prefs.applyRemote({ revision: 2, changed: { theme: null } });

    assert.equal(prefs.get('theme', 'claude'), 'claude');
});

test('a frame with no usable revision is ignored', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, {})]);
    await prefs.hydrate(api);

    assert.equal(prefs.applyRemote({ changed: { theme: 'matrix' } }), false);
    assert.equal(prefs.applyRemote({ revision: 'two', changed: { theme: 'x' } }), false);
    assert.equal(prefs.applyRemote(null), false);
    assert.equal(prefs.get('theme'), undefined);
});


test('a deliberate choice applies locally and reports itself pending', async () => {
    const prefs = loadModule();
    let resolveSave;
    const api = {
        sent: [],
        async call(endpoint, options = {}) {
            api.sent.push({ endpoint, options });
            if (!options.method) return block(1, {});
            return await new Promise((resolve) => { resolveSave = resolve; });
        },
    };
    await prefs.hydrate(api);

    const saving = prefs.set('sidebar_density', 'compact', api);

    assert.equal(prefs.get('sidebar_density'), 'compact');
    assert.equal(prefs.stateFor('sidebar_density'), prefs.PENDING);

    resolveSave({ status: 'committed', revision: 2, values: { sidebar_density: 'compact' } });
    await saving;

    assert.equal(prefs.stateFor('sidebar_density'), prefs.COMMITTED);
    assert.equal(prefs.revision(), 2);
});

test('the patch carries only the changed field and the held revision', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(4, { theme: 'claude', sidebar_density: 'cozy' }),
        { status: 'committed', revision: 5, values: { theme: 'claude', sidebar_density: 'compact' } },
    ]);
    await prefs.hydrate(api);

    await prefs.set('sidebar_density', 'compact', api);

    const body = api.sent[1].options.body;
    assert.deepEqual(body.changes, { sidebar_density: 'compact' },
        'the whole view was sent; that overwrites fields the user never displayed');
    assert.equal(body.expected_revision, 4);
    assert.equal(body.client_id, prefs.clientId);
});

test('a failed save keeps the users value visible and offers a retry', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        new Error('network down'),
        { status: 'committed', revision: 2, values: { theme: 'matrix' } },
    ]);
    await prefs.hydrate(api);

    const failed = await prefs.set('theme', 'matrix', api);

    assert.equal(failed.status, 'failed');
    assert.equal(prefs.stateFor('theme'), prefs.FAILED);
    assert.equal(prefs.get('theme'), 'matrix', 'the users choice vanished from the control');
    assert.equal(prefs.committedValue('theme'), 'claude',
        'the committed setting is still readable beside the unsaved one');

    const retried = await prefs.retry('theme', api);
    assert.equal(retried.status, 'committed');
    assert.equal(prefs.stateFor('theme'), prefs.COMMITTED);
});

test('a stale revision refusal keeps both values and does not retry blindly', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        staleError(7, { theme: 'set-by-another-device' }),
    ]);
    await prefs.hydrate(api);

    const result = await prefs.set('theme', 'matrix', api);

    assert.equal(result.status, 'stale_revision');
    assert.equal(api.sent.length, 2, 'the module retried a conflict on its own');
    assert.equal(prefs.stateFor('theme'), prefs.CONFLICT);
    assert.equal(prefs.get('theme'), 'matrix');
    assert.equal(prefs.committedValue('theme'), 'set-by-another-device');
    assert.equal(prefs.revision(), 7);
});

test('discarding a local edit leaves the committed value', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        staleError(7, { theme: 'set-by-another-device' }),
    ]);
    await prefs.hydrate(api);
    await prefs.set('theme', 'matrix', api);

    prefs.discardLocal('theme');

    assert.equal(prefs.stateFor('theme'), prefs.COMMITTED);
    assert.equal(prefs.get('theme'), 'set-by-another-device');
});

test('a received change for a field with an unsaved edit becomes a conflict', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, { theme: 'claude' }), new Error('network down')]);
    await prefs.hydrate(api);
    await prefs.set('theme', 'matrix', api);
    assert.equal(prefs.stateFor('theme'), prefs.FAILED);

    prefs.applyRemote({ revision: 2, changed: { theme: 'from-another-device' } });

    assert.equal(prefs.stateFor('theme'), prefs.CONFLICT);
    assert.equal(prefs.get('theme'), 'matrix');
    assert.equal(prefs.committedValue('theme'), 'from-another-device');
});


test('a re-read that left before a save and lands after it is dropped', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        { status: 'committed', revision: 2, values: { theme: 'matrix' } },
        block(1, { theme: 'claude' }),
    ]);
    await prefs.hydrate(api);
    await prefs.set('theme', 'matrix', api);
    await prefs.hydrate(api);

    assert.equal(prefs.get('theme'), 'matrix', 'a stale re-read rolled the saved theme back');
    assert.equal(prefs.revision(), 2);
});

test('server values win on a refresh', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        block(5, { theme: 'matrix', sidebar_density: 'compact' }),
    ]);
    await prefs.hydrate(api);
    await prefs.hydrate(api);

    assert.equal(prefs.get('theme'), 'matrix');
    assert.equal(prefs.get('sidebar_density'), 'compact');
    assert.equal(prefs.revision(), 5);
});

test('a refresh turns a failed edit the server disagrees with into a conflict', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        new Error('network down'),
        block(4, { theme: 'chosen-on-another-device' }),
    ]);
    await prefs.hydrate(api);
    await prefs.set('theme', 'matrix', api);
    assert.equal(prefs.stateFor('theme'), prefs.FAILED);

    await prefs.hydrate(api);

    assert.equal(prefs.stateFor('theme'), prefs.CONFLICT);
    assert.equal(prefs.get('theme'), 'matrix', 'the users unsaved edit was dropped');
    assert.equal(prefs.committedValue('theme'), 'chosen-on-another-device');
});

test('a refresh never silently re-sends a failed edit', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        new Error('network down'),
        block(4, { theme: 'chosen-on-another-device' }),
    ]);
    await prefs.hydrate(api);
    await prefs.set('theme', 'matrix', api);
    await prefs.hydrate(api);

    const writes = api.sent.filter((entry) => entry.options.method);
    assert.equal(writes.length, 1,
        'the reconnect re-sent an unsaved edit on its own; that overwrites '
        + 'whatever another device committed while this one was offline');
});

test('a refresh clears a failed edit the server turns out to agree with', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(1, { theme: 'claude' }),
        new Error('the response was lost, but the write may have landed'),
        block(2, { theme: 'matrix' }),
    ]);
    await prefs.hydrate(api);
    await prefs.set('theme', 'matrix', api);
    await prefs.hydrate(api);

    assert.equal(prefs.stateFor('theme'), prefs.COMMITTED);
    assert.equal(prefs.get('theme'), 'matrix');
});

test('a refresh leaves a save that is still in flight alone', async () => {
    const prefs = loadModule();
    let resolveSave;
    const api = {
        sent: [],
        responses: [block(1, { theme: 'claude' }), block(3, { theme: 'other' })],
        async call(endpoint, options = {}) {
            api.sent.push({ endpoint, options });
            if (options.method) {
                return await new Promise((resolve) => { resolveSave = resolve; });
            }
            return api.responses.shift();
        },
    };
    await prefs.hydrate(api);
    const saving = prefs.set('theme', 'matrix', api);
    await prefs.hydrate(api);

    assert.equal(prefs.stateFor('theme'), prefs.PENDING);

    resolveSave({ status: 'committed', revision: 4, values: { theme: 'matrix' } });
    await saving;
    assert.equal(prefs.stateFor('theme'), prefs.COMMITTED);
});

test('a refresh never uploads this browsers state', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, { theme: 'claude' }), block(2, { theme: 'matrix' })]);
    await prefs.hydrate(api);
    await prefs.hydrate(api);

    const writes = api.sent.filter((entry) => entry.options.method);
    assert.equal(writes.length, 0,
        'a reconnect uploaded an old whole-browser snapshot');
});

test('a read is answered from memory and never fetches', async () => {
    const prefs = loadModule();
    const api = makeApi([block(3, { theme: 'matrix' })]);
    await prefs.hydrate(api);

    for (let i = 0; i < 100; i += 1) prefs.get('theme');

    assert.equal(api.sent.length, 1);
});

test('a listener that throws does not stop the others being told', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, {})]);
    await prefs.hydrate(api);

    const seen = [];
    prefs.subscribe(() => { throw new Error('this control is broken'); });
    prefs.subscribe((name, value) => { seen.push([name, value]); });

    prefs.applyRemote({ revision: 2, changed: { theme: 'matrix' } });

    assert.deepEqual(seen, [['theme', 'matrix']]);
});

test('unsubscribing stops the listener', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, {})]);
    await prefs.hydrate(api);

    let calls = 0;
    const off = prefs.subscribe(() => { calls += 1; });
    prefs.applyRemote({ revision: 2, changed: { theme: 'a' } });
    off();
    prefs.applyRemote({ revision: 3, changed: { theme: 'b' } });

    assert.equal(calls, 1);
});


test('hydrate and set with no argument go through the page API client', async () => {
    const prefs = loadModule();
    const api = makeApi([block(1, { theme: 'claude' }), block(2, { theme: 'matrix' })]);
    delete globalThis.api;
    globalThis.API = api;
    try {
        assert.equal(await prefs.hydrate(), prefs.HYDRATED,
            'hydrate() with no argument did not reach window.API');
        assert.equal(api.sent[0].endpoint, '/preferences');
        const result = await prefs.set('theme', 'matrix');
        assert.notEqual(result.status, 'refused', 'set() with no argument refused');
        assert.equal(api.sent[1].options.method, 'PATCH');
    } finally {
        delete globalThis.API;
    }
});

test('no client script reaches for the lowercase api global', () => {
    const dir = path.join(here, '..', 'client', 'js');
    const offenders = [];
    const walk = (at) => {
        for (const entry of fs.readdirSync(at, { withFileTypes: true })) {
            const full = path.join(at, entry.name);
            if (entry.isDirectory()) walk(full);
            else if (entry.name.endsWith('.js')
                && /\b(?:window|globalThis)\.api\b/.test(fs.readFileSync(full, 'utf8'))) {
                offenders.push(path.relative(dir, full));
            }
        }
    };
    walk(dir);
    assert.ok(fs.readdirSync(dir).some((name) => name === 'api.js'),
        'client/js/api.js not found, so this scan looked at nothing');
    assert.deepEqual(offenders, []);
});

test('app.js hands the page API client to Preferences.hydrate', () => {
    const src = fs.readFileSync(path.join(here, '..', 'client', 'js', 'app.js'), 'utf8');
    assert.ok(src.includes('Preferences.hydrate(window.API)'),
        'app.js no longer hydrates preferences through window.API');
    const onLogin = src.slice(src.indexOf("addEventListener('authenticated'"));
    assert.ok(/^[^]*?_initAuthenticatedState\(\)/.test(onLogin.slice(0, 600)),
        'a login no longer runs the authenticated bring-up');
    const bringUp = src.slice(src.indexOf('async _initAuthenticatedState()'));
    assert.ok(bringUp.slice(0, bringUp.indexOf('\n    }\n')).includes('this._hydratePreferences()'),
        'the authenticated bring-up no longer hydrates preferences');
});


test('setMany sends one PATCH with both fields and one revision', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(3, { session_rail: ['a', 'b'] }),
        { status: 'committed', schema_version: 1, revision: 4, values: { session_rail: ['a'], session_rail_bottom: ['b'] } },
    ]);
    await prefs.hydrate(api);
    const result = await prefs.setMany({ session_rail: ['a'], session_rail_bottom: ['b'] }, api);
    assert.equal(result.status, 'committed');
    const patches = api.sent.filter((r) => r.options.method === 'PATCH');
    assert.equal(patches.length, 1);
    assert.deepEqual(patches[0].options.body.changes, { session_rail: ['a'], session_rail_bottom: ['b'] });
    assert.equal(patches[0].options.body.expected_revision, 3);
    assert.equal(prefs.revision(), 4);
    assert.deepEqual(prefs.get('session_rail_bottom'), ['b']);
});

test('setMany refused 409 adopts the server value and marks BOTH fields conflicted', async () => {
    const prefs = loadModule();
    const api = makeApi([
        block(3, { session_rail: ['a', 'b'] }),
        staleError(4, { session_rail: ['a', 'b', 'c'] }),
    ]);
    await prefs.hydrate(api);
    const result = await prefs.setMany({ session_rail: ['a'], session_rail_bottom: ['b'] }, api);
    assert.equal(result.status, 'stale_revision');
    assert.equal(prefs.revision(), 4);
    assert.deepEqual(prefs.committedValue('session_rail'), ['a', 'b', 'c']);
    assert.equal(api.sent.filter((r) => r.options.method === 'PATCH').length, 1);
});

test('setMany with a failing request marks both fields failed', async () => {
    const prefs = loadModule();
    const api = makeApi([block(3, {}), new Error('boom')]);
    await prefs.hydrate(api);
    const result = await prefs.setMany({ x: 1, y: 2 }, api);
    assert.equal(result.status, 'failed');
    assert.equal(prefs.revision(), 3);
});
