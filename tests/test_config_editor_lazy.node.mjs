
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

function loadLazy(fetchImpl) {
    const calls = [];
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    fakeWindow.API = {
        async getConfigFileTree(root, projectPath, opts) {
            calls.push({ root, projectPath, opts });
            return await fetchImpl(root, projectPath, opts);
        },
    };
    const context = { window: fakeWindow, console: { log() {}, warn() {} } };
    vm.createContext(context);
    for (const file of ['config-editor-roots.js', 'config-editor-lazy.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(__dirname, '..', 'client', 'js', file), 'utf8'),
            context,
        );
    }
    return { lazy: fakeWindow.ConfigEditorLazy, calls };
}

const NEVER = () => {
    throw new Error('the fetch must not have been attempted');
};

await test('a directory the server did not look inside needs a fetch', () => {
    const { lazy } = loadLazy(NEVER);
    assert.equal(lazy.needsFetch({ is_dir: true, children_loaded: false }), true);
});

await test('COMPATIBILITY: an absent children_loaded is treated as loaded', () => {
    const { lazy } = loadLazy(NEVER);
    assert.equal(lazy.needsFetch({ is_dir: true }), false);
    assert.equal(lazy.needsFetch({ is_dir: true, children_loaded: undefined }), false);
    assert.equal(lazy.needsFetch({ is_dir: true, children_loaded: true }), false);
});

await test('a file never needs a fetch, whatever the flag says', () => {
    const { lazy } = loadLazy(NEVER);
    assert.equal(lazy.needsFetch({ is_dir: false, children_loaded: false }), false);
});

await test('children already in hand are returned without a request', async () => {
    const { lazy, calls } = loadLazy(NEVER);
    const node = { is_dir: true, rel_path: 'src', children_loaded: true, children: [{ name: 'a' }] };
    const verdict = await lazy.childrenFor('workdir', node, '/p');
    assert.equal(verdict.status, 'have');
    assert.equal(verdict.nodes.length, 1);
    assert.equal(calls.length, 0, 'nothing should have been requested');
});

await test('an unloaded directory is fetched at depth 1, by its own rel_path', async () => {
    const { lazy, calls } = loadLazy(async () => ({ tree: [{ name: 'app.py' }] }));
    const node = { is_dir: true, rel_path: 'src', children_loaded: false, children: [] };
    const verdict = await lazy.childrenFor('workdir', node, '/p');
    assert.equal(verdict.status, 'loaded');
    assert.deepEqual(verdict.nodes.map((n) => n.name), ['app.py']);
    assert.equal(calls.length, 1);
    assert.equal(calls[0].root, 'workdir');
    assert.equal(calls[0].projectPath, '/p');
    assert.equal(calls[0].opts.path, 'src');
    assert.equal(calls[0].opts.depth, 1,
        'asking for more than one level prefetches what nobody opened');
});

await test('a fetched directory with no entries is a MEASURED empty one', async () => {
    const { lazy } = loadLazy(async () => ({ tree: [] }));
    const node = { is_dir: true, rel_path: 'empty', children_loaded: false, children: [] };
    const verdict = await lazy.childrenFor('workdir', node, '/p');
    assert.equal(verdict.status, 'loaded');
    assert.deepEqual(verdict.nodes, []);
});

await test('NEGATIVE CONTROL: a failed request is not an empty directory', async () => {
    const err = new Error("'locked' could not be read: Permission denied");
    err.status = 503;
    const { lazy } = loadLazy(async () => { throw err; });
    const node = { is_dir: true, rel_path: 'locked', children_loaded: false, children: [] };
    const verdict = await lazy.childrenFor('workdir', node, '/p');
    assert.equal(verdict.status, 'failed',
        'a request that did not answer must never report as a successful empty read');
    assert.equal(verdict.nodes, undefined, 'there are no nodes to render');
    assert.ok(verdict.message.includes('Permission denied'),
        'the server\'s own reason must reach the user');
    assert.ok(!/empty/i.test(verdict.message));
});

await test('NEGATIVE CONTROL: a network failure with no status still says so', async () => {
    const { lazy } = loadLazy(async () => { throw new Error('Failed to fetch'); });
    const node = { is_dir: true, rel_path: 'src', children_loaded: false, children: [] };
    const verdict = await lazy.childrenFor('workdir', node, '/p');
    assert.equal(verdict.status, 'failed');
    assert.ok(verdict.message.length > 0);
});

await test('a server-reported list_error is rendered without asking again', async () => {
    const { lazy, calls } = loadLazy(NEVER);
    const node = {
        is_dir: true, rel_path: 'locked', children_loaded: false,
        children: [], list_error: 'Permission denied',
    };
    const verdict = await lazy.childrenFor('workdir', node, '/p');
    assert.equal(verdict.status, 'list_error');
    assert.ok(verdict.message.includes('Permission denied'));
    assert.equal(calls.length, 0,
        'the server already measured this one; asking again just fails differently');
});

await test('the three failure-ish outcomes render three different sentences', () => {
    const { lazy } = loadLazy(NEVER);
    void lazy;
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const ctx = { window: fakeWindow, console: { log() {} } };
    vm.createContext(ctx);
    vm.runInContext(
        fs.readFileSync(path.join(__dirname, '..', 'client', 'js', 'config-editor-roots.js'), 'utf8'),
        ctx,
    );
    const Roots = fakeWindow.ConfigEditorRoots;
    const sentences = new Set([
        Roots.listErrorNotice('Permission denied'),
        Roots.expandFailedNotice('Permission denied'),
        Roots.workdirUnavailableNotice('project files', '/p'),
    ]);
    assert.equal(sentences.size, 3, 'each outcome needs its own wording');
});

await test('the panel wires the expansion through this module, not its own fetch', () => {
    const panel = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'config-editor-panel.js'),
        'utf8',
    );
    assert.ok(panel.includes('window.ConfigEditorLazy.childrenFor'),
        'the panel must expand through the tested module');
    assert.ok(panel.includes('ConfigEditorLazy.FETCH_DEPTH'),
        'the root listing must be shallow too, or the server still walks everything');
    assert.ok(/verdict\.status === 'failed'/.test(panel),
        'the panel must render the could-not-load outcome rather than dropping it');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
