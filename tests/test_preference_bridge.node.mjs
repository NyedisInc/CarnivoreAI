
import { strict as assert } from 'node:assert';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(here, '..', 'client', 'js', 'preference-bridge.js');

function makePreferences({ values = {}, hydrated = true, setResult = null, throwOnSet = false } = {}) {
    const saved = [];
    const listeners = [];
    return {
        HYDRATED: 'hydrated',
        saved,
        listeners,
        status() { return hydrated ? 'hydrated' : 'read_failed'; },
        get(name, fallback) {
            return Object.prototype.hasOwnProperty.call(values, name)
                ? values[name] : fallback;
        },
        async set(name, value) {
            if (throwOnSet) throw new Error('transport exploded');
            saved.push({ name, value });
            return setResult || { status: 'committed' };
        },
        subscribe(fn) { listeners.push(fn); return () => {}; },
    };
}

function loadModule(preferences) {
    delete require.cache[require.resolve(MODULE_PATH)];
    delete globalThis.PreferenceBridge;
    if (preferences === null) delete globalThis.Preferences;
    else globalThis.Preferences = preferences;
    return require(MODULE_PATH);
}

const localReader = (value) => () => value;


test('a field the server does not hold falls through to local, never to a default', () => {
    const mod = loadModule(makePreferences({ values: {} }));
    assert.equal(mod.read('sidebar_density', localReader('detailed')), 'detailed');
    assert.equal(mod.isShared('sidebar_density'), false);
});

test('a failed hydration falls through to local rather than resetting the control', () => {
    const mod = loadModule(makePreferences({
        values: { sidebar_density: 'compact' }, hydrated: false,
    }));
    assert.equal(mod.read('sidebar_density', localReader('detailed')), 'detailed');
    assert.equal(mod.isShared('sidebar_density'), false);
});

test('with no preference layer at all the control behaves exactly as before', () => {
    const mod = loadModule(null);
    assert.equal(mod.read('sidebar_density', localReader('detailed')), 'detailed');
});

test('a shared value wins over the local one', () => {
    const mod = loadModule(makePreferences({ values: { sidebar_density: 'compact' } }));
    assert.equal(mod.read('sidebar_density', localReader('detailed')), 'compact');
    assert.equal(mod.isShared('sidebar_density'), true);
});

test('a shared false is a value, not an absence', () => {
    const mod = loadModule(makePreferences({ values: { sidebar_pinned: false } }));
    assert.equal(mod.read('sidebar_pinned', localReader(true)), false);
});

test('a shared empty string is a value, not an absence', () => {
    const mod = loadModule(makePreferences({ values: { launch_last_model: '' } }));
    assert.equal(mod.read('launch_last_model', localReader('some/model')), '');
});

test('NEGATIVE CONTROL: reading never saves anything', () => {
    const prefs = makePreferences({ values: { sidebar_density: 'compact' } });
    const mod = loadModule(prefs);
    mod.read('sidebar_density', localReader('detailed'));
    mod.read('sidebar_pinned', localReader(true));
    mod.isShared('theme');
    assert.equal(prefs.saved.length, 0,
        'the bridge uploaded a value nobody asked it to');
});

test('a write mirrors to local FIRST and then shares', () => {
    const prefs = makePreferences();
    const mod = loadModule(prefs);
    const order = [];
    const localWriter = () => order.push('local');
    prefs.set = async (name, value) => {
        order.push('shared');
        prefs.saved.push({ name, value });
        return { status: 'committed' };
    };
    return mod.write('sidebar_density', 'compact', localWriter).then((result) => {
        assert.deepEqual(order, ['local', 'shared']);
        assert.equal(result.status, 'committed');
        assert.deepEqual(prefs.saved, [{ name: 'sidebar_density', value: 'compact' }]);
    });
});

test('a failed share still leaves the local copy written', async () => {
    const prefs = makePreferences({ setResult: { status: 'failed' } });
    const mod = loadModule(prefs);
    let wrote = false;
    const result = await mod.write('sidebar_density', 'compact', () => { wrote = true; });
    assert.equal(wrote, true, 'the user lost the setting they just chose');
    assert.equal(result.status, 'failed');
});

test('a transport that throws is an answer, not a rejection', async () => {
    const mod = loadModule(makePreferences({ throwOnSet: true }));
    let wrote = false;
    const result = await mod.write('sidebar_density', 'compact', () => { wrote = true; });
    assert.equal(wrote, true);
    assert.equal(result.status, 'failed');
});

test('a local writer that throws does not stop the shared save', async () => {
    const prefs = makePreferences();
    const mod = loadModule(prefs);
    const result = await mod.write('sidebar_density', 'compact', () => {
        throw new Error('storage disabled');
    });
    assert.equal(result.status, 'committed');
    assert.deepEqual(prefs.saved, [{ name: 'sidebar_density', value: 'compact' }]);
});

test('with no preference layer a write is local only and says so', async () => {
    const mod = loadModule(null);
    let wrote = false;
    const result = await mod.write('sidebar_density', 'compact', () => { wrote = true; });
    assert.equal(wrote, true);
    assert.equal(result.status, 'local_only');
});

test('follow repaints on its own field and ignores every other one', () => {
    const prefs = makePreferences();
    const mod = loadModule(prefs);
    const seen = [];
    mod.follow('sidebar_density', (value) => seen.push(value));
    prefs.listeners[0]('sidebar_density', 'detailed');
    prefs.listeners[0]('theme', 'matrix');
    assert.deepEqual(seen, ['detailed']);
});

test('follow with no preference layer answers a no-op unsubscribe', () => {
    const mod = loadModule(null);
    const off = mod.follow('sidebar_density', () => {});
    assert.equal(typeof off, 'function');
    off();
});

test('writeMany runs every local writer and saves all fields as ONE setMany', async () => {
    const prefs = makePreferences();
    const calls = [];
    prefs.setMany = async (changes) => { calls.push(changes); return { status: 'committed' }; };
    const mod = loadModule(prefs);
    const local = [];
    const result = await mod.writeMany([
        { field: 'a', value: 1, localWriter: () => local.push('a') },
        { field: 'b', value: null, localWriter: () => local.push('b') },
    ]);
    assert.equal(result.status, 'committed');
    assert.deepEqual(local, ['a', 'b']);
    assert.deepEqual(calls, [{ a: 1, b: null }]);
    assert.equal(prefs.saved.length, 0);
});

test('writeMany with no preference layer is local only', async () => {
    const mod = loadModule(null);
    const result = await mod.writeMany([{ field: 'a', value: 1, localWriter: () => {} }]);
    assert.equal(result.status, 'local_only');
});
