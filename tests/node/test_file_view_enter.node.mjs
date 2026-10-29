
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../..');
let failures = 0;

async function test(name, fn) {
    try { await fn(); console.log(`ok - ${name}`); } catch (err) {
        failures++; console.error(`NOT OK - ${name}`); console.error(err && err.stack ? err.stack : err);
    }
}

function load() {
    const calls = { collapsed: [], opened: [], cleared: 0, loads: 0 };
    const win = {};
    win.window = win;
    win.ConfigEditorTreeState = { setNodeCollapsed: (k, v) => calls.collapsed.push([k, v]) };
    const ctx = { window: win, console: { log() {} }, document: { createElement: () => ({ style: {}, appendChild() {} }) } };
    vm.createContext(ctx);
    for (const f of ['config-editor-roots.js', 'config-editor-filter.js', 'config-editor-panel.js']) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, 'client', 'js', f), 'utf8'), ctx);
    }
    const panel = win.ConfigEditorPanel;
    let query = '';
    panel._query = () => query;
    panel._loadTree = async () => { calls.loads++; };
    panel._openFile = (...a) => calls.opened.push(a);
    panel.treeEl = { querySelectorAll: () => [] };
    panel._header = { setScope: () => {}, clearQuery: () => { calls.cleared++; query = ''; panel._treeLoading = panel._loadTree(); } };
    return { panel, calls, win, type: (q) => { query = q; panel._treeLoading = Promise.resolve(); } };
}

const TREE = [
    { name: 'docs', rel_path: 'docs', is_dir: true, children: [] },
    { name: 'src', rel_path: 'src', is_dir: true, children: [
        { name: 'api', rel_path: 'src/api', is_dir: true, children: [] },
        { name: 'main.py', rel_path: 'src/main.py', is_dir: false, read_only: false },
    ] },
];

await test('first name match is the folder itself, depth first in draw order', () => {
    const { panel } = load();
    assert.equal(panel._firstNameMatch(TREE, 'src').rel_path, 'src');
    assert.equal(panel._firstNameMatch(TREE, 'ap').rel_path, 'src/api');
    assert.equal(panel._firstNameMatch(TREE, 'zzz'), null);
});

await test('Enter on a folder match opens it and its ancestors, clears the text, redraws', async () => {
    const { panel, calls, type } = load();
    type('api');
    panel._best = { rootId: 'workdir', node: TREE[1].children[0], projectPath: '/p' };
    await panel._enterBestMatch();
    assert.deepEqual(calls.collapsed, [['workdir:src', false], ['workdir:src/api', false]]);
    assert.equal(calls.cleared, 1);
    assert.equal(calls.loads, 1);
    assert.equal(calls.opened.length, 0);
});

await test('Enter on a file match opens it exactly as a click does', async () => {
    const { panel, calls, type } = load();
    type('main');
    panel._best = { rootId: 'workdir', node: TREE[1].children[1], projectPath: '/p' };
    await panel._enterBestMatch();
    assert.deepEqual(calls.opened, [['workdir', 'src/main.py', false, '/p']]);
    assert.equal(calls.cleared, 0);
});

await test('Enter with no match, or no typed text, does nothing', async () => {
    const { panel, calls, type } = load();
    type('zzz');
    panel._best = null;
    await panel._enterBestMatch();
    type('');
    panel._best = { rootId: 'workdir', node: TREE[0], projectPath: '/p' };
    await panel._enterBestMatch();
    assert.deepEqual([calls.collapsed.length, calls.cleared, calls.opened.length], [0, 0, 0]);
});

await test('the header hands Enter to the drawer and the drawer wires it', () => {
    const header = fs.readFileSync(path.join(ROOT, 'web', 'src', 'lib', 'file-drawer', 'FileDrawerHeader.svelte'), 'utf8');
    const panel = fs.readFileSync(path.join(ROOT, 'client', 'js', 'config-editor-panel.js'), 'utf8');
    assert.ok(/key === 'Enter'[\s\S]{0,80}onSubmit/.test(header));
    assert.ok(panel.includes('onSubmit: () => this._enterBestMatch()'));
});


const file = (name, rel) => ({ name, rel_path: rel, is_dir: false, read_only: false });
const dir = (name, rel, children) => ({ name, rel_path: rel, is_dir: true, children });

function loadScoped(tree) {
    const env = load();
    const { panel, win } = env;
    const seen = { paths: [], scopes: [] };
    let query = '';
    delete panel._loadTree;
    panel._query = () => query;
    panel._projectContext = () => ({ path: '/p', reason: '' });
    panel._prefs = () => ({ hideDot: false, hideIgnored: false });
    panel._buildNodeEl = () => ({});
    panel.treeEl = { innerHTML: '', appendChild() {}, querySelectorAll: () => [] };
    win.ConfigEditorRows = { noticeLi: () => ({}), errorEl: () => ({}) };
    const under = (nodes, rel) => {
        if (!rel) return nodes;
        for (const n of nodes) {
            if (n.rel_path === rel) return n.children || [];
            if (n.is_dir && rel.startsWith(`${n.rel_path}/`)) return under(n.children || [], rel);
        }
        return [];
    };
    win.API = { findConfigFiles: async (root, _p, o) => {
        if (root !== 'workdir') return { tree: [] };
        seen.paths.push(o.path);
        return { tree: under(tree, o.path), ignore_status: 'ok' };
    } };
    panel._header = {
        setScope: (label) => seen.scopes.push(label), setIgnoreStatus() {},
        clearQuery: () => { query = ''; panel._treeLoading = panel._loadTree(); },
    };
    const type = async (q) => { query = q; panel._treeLoading = panel._loadTree(); await panel._treeLoading; };
    return { ...env, panel, seen, type };
}

const WALK = [
    dir('b', 'b', [file('x.txt', 'b/x.txt')]),
    dir('a', 'a', [dir('sub', 'a/sub', [file('x.txt', 'a/sub/x.txt')]), file('x.txt', 'a/x.txt')]),
];

await test('after Enter goes into folder a, a name found both inside and outside a picks the one inside', async () => {
    const { panel, calls, seen, type } = loadScoped(WALK);
    await type('x.txt');
    assert.equal(panel._best.node.rel_path, 'b/x.txt', 'unscoped, tree order wins');
    await type('a');
    assert.equal(panel._best.node.rel_path, 'a');
    await panel._enterBestMatch();
    assert.equal(JSON.stringify(panel._scope), JSON.stringify({ rootId: 'workdir', relPath: 'a' }));
    assert.deepEqual(seen.scopes, ['a/']);
    await type('x.txt');
    assert.equal(seen.paths.at(-1), 'a', 'the search is asked of the scope folder only');
    await panel._enterBestMatch();
    assert.deepEqual(calls.opened, [['workdir', 'a/x.txt', false, '/p']]);
});

await test('scoped matches rank direct children before deeper ones', async () => {
    const { panel, type } = loadScoped(WALK);
    panel._scope = { rootId: 'workdir', relPath: 'a' };
    await type('x.txt');
    assert.equal(panel._best.node.rel_path, 'a/x.txt', 'not a/sub/x.txt, which the tree draws first');
});

await test('the scope applies only to its own root; others are not searched', async () => {
    const { panel, seen, type } = loadScoped(WALK);
    panel._scope = { rootId: 'workdir', relPath: 'a' };
    await type('x.txt');
    assert.deepEqual([...new Set(seen.paths)], ['a']);
});

await test('Backspace on an empty field goes up one level, then to the whole tree; Escape clears it', async () => {
    const { panel, seen } = loadScoped(WALK);
    panel._scope = { rootId: 'workdir', relPath: 'a/sub' };
    panel._scopeUp();
    assert.equal(JSON.stringify(panel._scope), JSON.stringify({ rootId: 'workdir', relPath: 'a' }));
    panel._scopeUp();
    assert.equal(panel._scope, null);
    assert.deepEqual(seen.scopes, ['a/', '']);
    panel._scope = { rootId: 'workdir', relPath: 'a' };
    panel._setScope(null);
    assert.equal(panel._scope, null);
    assert.equal(seen.scopes.at(-1), '');
});

await test('the header routes Backspace-on-empty and Escape-with-nothing-typed to the scope', () => {
    const header = fs.readFileSync(path.join(ROOT, 'web', 'src', 'lib', 'file-drawer', 'FileDrawerHeader.svelte'), 'utf8');
    const panel = fs.readFileSync(path.join(ROOT, 'client', 'js', 'config-editor-panel.js'), 'utf8');
    assert.ok(/key === 'Backspace' && !text && scopeLabel[\s\S]{0,80}onScopeUp/.test(header));
    assert.ok(/key === 'Escape' && scopeLabel[\s\S]{0,80}onScopeClear/.test(header));
    assert.ok(/if \(scopeLabel\) \{\s*onScopeClear/.test(header));
    assert.ok(panel.includes('onScopeUp: () => this._scopeUp()'));
});

if (failures) { console.error(`${failures} failed`); process.exit(1); }
