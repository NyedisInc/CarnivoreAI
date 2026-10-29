import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import { JSDOM } from '../web/node_modules/jsdom/lib/api.js';

const names = (list) => Array.from(list, (n) => n.name);
const read = (file) => readFileSync(new URL(`../client/js/${file}`, import.meta.url), 'utf8');

function harness({ tree = {}, ignoreStatus = 'ok' } = {}) {
    const dom = new JSDOM('<div id="config-editor-overlay" hidden><div class="config-editor-picker-content">'
        + '<div id="config-editor-header"></div><div id="config-editor-tree"></div></div></div>'
        + '<div id="terminal-container" style="position:relative"></div><div id="cell"></div>');
    const store = new Map();
    const window = {
        console,
        localStorage: {
            getItem: (k) => (store.has(k) ? store.get(k) : null),
            setItem: (k, v) => store.set(k, String(v)),
        },
        ModalStack: { push() {}, pop() {}, depth: () => 0 },
        CloudeI18n: { t: (key, params) => `${key}${params ? JSON.stringify(params) : ''}` },
    };
    window.window = window;
    const events = new EventTarget();
    window.addEventListener = events.addEventListener.bind(events);
    window.removeEventListener = events.removeEventListener.bind(events);
    window.dispatchEvent = events.dispatchEvent.bind(events);
    const document = dom.window.document;
    const ctx = vm.createContext({ window, document, console, localStorage: window.localStorage,
        setTimeout, clearTimeout, Map, Set, Promise });
    for (const file of ['session-status-ui.js', 'config-editor-tree-state.js', 'config-editor-roots.js',
        'config-editor-lazy.js', 'config-editor-filter.js', 'config-editor-rows.js',
        'config-editor-modal.js', 'config-editor-panel.js', 'config-editor-loader.js']) {
        vm.runInContext(read(file), ctx);
    }
    const calls = [];
    window.API = {
        async getConfigFileTree(root, project, opts) {
            calls.push({ kind: 'tree', root, project, opts });
            const key = `${root}:${(opts && opts.path) || ''}`;
            return { tree: structuredClone(tree[key] || []), ignore_status: ignoreStatus };
        },
        async findConfigFiles(root, project, opts) {
            calls.push({ kind: 'find', root, project, opts });
            return { tree: structuredClone(tree[`find:${root}`] || []), truncated: false, ignore_status: ignoreStatus };
        },
        async readConfigFile() {
            return { content: 'hello', is_executable: false, is_sensitive: false, read_only: false, size: 5 };
        },
    };
    window.CodeMirrorBundle = { createEditor: () => ({ getValue: () => 'hello', destroy() {}, focus() {} }) };
    const header = { q: '', prefs: { hideDot: false, hideIgnored: false }, status: null };
    window.CloudeWeb = { fileDrawer: { mountHeader: () => ({
        prefs: () => ({ ...header.prefs }),
        query: () => header.q,
        clearQuery: () => { header.q = ''; },
        setIgnoreStatus: (s) => { header.status = s; },
        escape: () => false,
    }) } };
    return { window, document, panel: window.ConfigEditorPanel, header, calls };
}

const file = (name, extra = {}) => ({ name, rel_path: name, is_dir: false, children: [], ...extra });
const dir = (name, children, extra = {}) => ({
    name, rel_path: name, is_dir: true, children, children_loaded: children !== null, ...extra,
});
const visibleNames = (document) => [...document.querySelectorAll('#config-editor-tree .config-editor-node-name')]
    .filter((el) => !el.closest('ul[hidden]'))
    .map((el) => el.textContent);
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const terminal = (path, host = null) => ({
    sessionActive: true, _currentSession: { working_dir: path }, host,
});


test('filterTree keeps the path to every name match, any case, and opens it', () => {
    const { window } = harness();
    const nodes = [dir('src', [dir('core', [file('Readme.md'), file('app.py')])]), file('README.md'), file('x.txt')];
    const found = window.ConfigEditorFilter.filterTree(nodes, 'readme', {});
    assert.equal(found.matches, 2);
    assert.deepEqual(names(found.nodes), ['src', 'README.md']);
    assert.equal(found.nodes[0].filter_expanded, true);
    assert.deepEqual(names(found.nodes[0].children[0].children), ['Readme.md']);
    assert.equal(nodes[0].children[0].children.length, 2, 'the input is not mutated');
});

test('filterTree keeps a folder whose own name matches whole and closed', () => {
    const { window } = harness();
    const found = window.ConfigEditorFilter.filterTree([dir('docs', [file('a.md')])], 'DOC', {});
    assert.equal(found.nodes[0].filter_expanded, false);
    assert.deepEqual(names(found.nodes[0].children), ['a.md']);
});

test('filterTree stops at its limit and says so', () => {
    const { window } = harness();
    const found = window.ConfigEditorFilter.filterTree([file('a1'), file('a2'), file('a3')], 'a', {}, 2);
    assert.equal(found.matches, 2);
    assert.equal(found.truncated, true);
});

test('the hide options hide only what they name, and only what git measured', () => {
    const { window } = harness();
    const f = window.ConfigEditorFilter;
    const nodes = [file('.env'), file('build.log', { is_ignored: true }), file('app.py', { is_ignored: false }),
        file('unknown.txt')];
    assert.deepEqual(names(f.visibleNodes(nodes, {})), ['.env', 'build.log', 'app.py', 'unknown.txt']);
    assert.deepEqual(names(f.visibleNodes(nodes, { hideDot: true })), ['build.log', 'app.py', 'unknown.txt']);
    assert.deepEqual(names(f.visibleNodes(nodes, { hideIgnored: true })), ['.env', 'app.py', 'unknown.txt']);
});


const TREE = {
    'user:': [dir('agents', null), file('CLAUDE.md'), file('.hidden-config')],
    'workdir:': [dir('dist', null, { is_ignored: true }), dir('src', null), file('.env', { is_sensitive: true }),
        file('trace.log', { is_ignored: true }), file('README.md')],
};

test('the drawer lists dot and ignored files by default, and hides each on request', async () => {
    const { panel, document, header, window } = harness({ tree: TREE });
    window.ConfigEditorTreeState.setNodeCollapsed('workdir:__root__', false);
    await panel.open(null, terminal('/proj'));
    await tick();
    const all = visibleNames(document);
    for (const name of ['.hidden-config', '.env', 'dist', 'trace.log', 'README.md']) assert.ok(all.includes(name), name);

    header.prefs = { hideDot: true, hideIgnored: false };
    await panel._loadTree();
    await tick();
    let shown = visibleNames(document);
    assert.ok(!shown.includes('.env') && !shown.includes('.hidden-config'), 'dot files hidden');
    assert.ok(shown.includes('dist') && shown.includes('trace.log'), 'ignored still shown');

    header.prefs = { hideDot: false, hideIgnored: true };
    await panel._loadTree();
    await tick();
    shown = visibleNames(document);
    assert.ok(!shown.includes('dist') && !shown.includes('trace.log'), 'ignored hidden');
    assert.ok(shown.includes('.env') && shown.includes('README.md'), 'the rest stays');
});

test('every listing asks git for ignore marks, and the header learns the answer', async () => {
    const { panel, header, calls } = harness({ tree: TREE, ignoreStatus: 'unavailable' });
    await panel.open(null, terminal('/proj'));
    assert.ok(calls.length > 0 && calls.every((c) => c.opts.ignored === true));
    assert.equal(header.status, 'unavailable');
});

test('a folder opened later is marked by git too, so hiding holds below the top', async () => {
    const tree = { ...TREE, 'workdir:src': [file('keep.py', { is_ignored: false }), file('gen.py', { is_ignored: true })] };
    const { panel, document, header, calls, window } = harness({ tree });
    window.ConfigEditorTreeState.setNodeCollapsed('workdir:__root__', false);
    header.prefs = { hideDot: false, hideIgnored: true };
    await panel.open(null, terminal('/proj'));
    await tick();
    const src = [...document.querySelectorAll('.config-editor-toggle')].find((t) => t.textContent.includes('src'));
    src.click();
    await tick(); await tick();
    const expansion = calls.find((c) => c.kind === 'tree' && c.opts.path === 'src');
    assert.ok(expansion, 'population check: the folder was fetched on open');
    assert.equal(expansion.opts.ignored, true, 'the expansion asks git as well');
    const shown = visibleNames(document);
    assert.ok(shown.includes('keep.py'));
    assert.ok(!shown.includes('gen.py'), 'an ignored file below the top is hidden');
});

test('a query renders the server search, with the way to each match open', async () => {
    const tree = { ...TREE,
        'find:workdir': [dir('src', [dir('core', [file('readme-core.md')], { children_loaded: false })],
            { children_loaded: false }), file('README.md')],
        'find:user': [],
    };
    const { panel, document, header, calls } = harness({ tree });
    await panel.open(null, terminal('/proj'));
    header.q = 'readme';
    await panel._loadTree();
    await tick();
    const finds = calls.filter((c) => c.kind === 'find');
    assert.deepEqual(finds.map((c) => c.opts.q).sort(), ['readme', 'readme']);
    const shown = visibleNames(document);
    assert.ok(shown.includes('readme-core.md'), 'the deep match is on screen');
    assert.ok(shown.includes('README.md'));
    assert.ok(!shown.includes('CLAUDE.md'), 'non-matches are gone');
    const src = [...document.querySelectorAll('.config-editor-toggle')].find((t) => t.textContent.includes('src'));
    assert.equal(src.getAttribute('aria-expanded'), 'true');

    header.q = 'zzz';
    tree['find:workdir'] = [];
    await panel._loadTree();
    assert.match(document.getElementById('config-editor-tree').textContent, /files\.drawer\.no_matches/);
});

test('collapse all closes every folder on screen and remembers it, roots excepted', async () => {
    const tree = { ...TREE, 'user:agents': [file('a.md')], 'workdir:src': [file('main.py')] };
    const { panel, document, window } = harness({ tree });
    window.ConfigEditorTreeState.setNodeCollapsed('workdir:__root__', false);
    window.ConfigEditorTreeState.setNodeCollapsed('workdir:src', false);
    window.ConfigEditorTreeState.setNodeCollapsed('user:agents', false);
    await panel.open(null, terminal('/proj'));
    await tick();
    const open = () => [...document.querySelectorAll('.config-editor-toggle:not(.config-editor-toggle--root)')]
        .filter((t) => t.getAttribute('aria-expanded') === 'true').length;
    assert.ok(open() >= 2, 'population check: folders are open before');

    panel.collapseAll();
    assert.equal(open(), 0);
    assert.ok([...document.querySelectorAll('.config-editor-toggle--root')]
        .every((t) => t.getAttribute('aria-expanded') === 'true'), 'roots stay open');
    const state = window.ConfigEditorTreeState;
    assert.equal(state.startsCollapsed('workdir', { name: 'src', rel_path: 'src' }), true);
    assert.equal(state.startsCollapsed('user', { name: 'agents', rel_path: 'agents' }), true);
    assert.equal(state.startsCollapsed('workdir', { name: '', rel_path: '' }, true), false, 'root remembered open');
});


test('the loader freezes the cell host, or the page terminal for the primary', async () => {
    const { window, document } = harness();
    let received = null;
    window.ModuleFamilies = { CONFIG_EDITOR: [] };
    window.ModuleLoader = { loadFamily: () => Promise.resolve() };
    const realPanel = window.ConfigEditorPanel;
    window.ConfigEditorPanel = { open: (_t, target) => { received = target; } };
    const cell = document.getElementById('cell');
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/a'), null, cell);
    assert.equal(received.host, cell);
    window.TerminalController = terminal('/b');
    await window.ConfigEditorLoader.openWhenReady(null, window.TerminalController, null);
    assert.equal(received.host, document.getElementById('terminal-container'));
    window.ConfigEditorPanel = realPanel;
});

test('opening a file closes the drawer and edits it inside that terminal', async () => {
    const { panel, document, window } = harness({ tree: TREE });
    const cell = document.getElementById('cell');
    const pushes = [];
    window.ModalStack.push = (el) => pushes.push(el);
    await panel.open(null, terminal('/proj', cell));
    await tick();
    document.querySelector('.config-editor-file[data-path="CLAUDE.md"]').click();
    await tick(); await tick();

    assert.equal(document.getElementById('config-editor-overlay').hidden, true, 'the drawer closed');
    const editor = document.querySelector('.config-editor-inplace');
    assert.ok(editor, 'an editor exists');
    assert.equal(editor.parentElement, cell, 'inside the cell the drawer was opened for');
    assert.equal(document.querySelector('.config-editor-modal-overlay'), null, 'not the full-screen modal');
    assert.equal(window.ConfigEditorModal.isInPlace(), true);
    assert.ok(!pushes.includes(editor), 'an in-terminal editor is not a page modal');

    document.getElementById('config-editor-modal-back').click();
    await tick();
    assert.equal(document.getElementById('config-editor-overlay').hidden, false);
    assert.equal(panel._editorHost(), cell);
    assert.ok(document.querySelector('.config-editor-inplace'), 'the editor stays');
    await panel.close();
    assert.ok(document.querySelector('.config-editor-inplace'), 'closing the drawer leaves the editor');

    editor.dispatchEvent(new document.defaultView.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await tick();
    assert.equal(document.querySelector('.config-editor-inplace'), null);
});

test('an editor in the page terminal goes away when that terminal moves to another folder', async () => {
    const { panel, document, window } = harness({ tree: TREE });
    const page = document.getElementById('terminal-container');
    window.TerminalController = { sessionActive: true, _currentSession: { session: { working_dir: '/proj' } } };
    await panel.open(null, terminal('/proj', page));
    await tick();
    document.querySelector('.config-editor-file[data-path="CLAUDE.md"]').click();
    await tick(); await tick();
    assert.equal(document.querySelector('.config-editor-inplace').parentElement, page);

    window.dispatchEvent(new Event('cloude:terminal-connection'));
    await tick();
    assert.ok(document.querySelector('.config-editor-inplace'), 'same folder: the editor stays');

    window.TerminalController._currentSession = { session: { working_dir: '/other' } };
    window.dispatchEvent(new Event('cloude:terminal-connection'));
    await tick();
    assert.equal(document.querySelector('.config-editor-inplace'), null, 'another folder: the editor closed');
});

test('with no terminal on the page the editor is the full-screen modal it was', async () => {
    const { panel, document } = harness({ tree: TREE });
    await panel.open(null, terminal('/proj', null));
    await tick();
    document.querySelector('.config-editor-file[data-path="CLAUDE.md"]').click();
    await tick(); await tick();
    assert.ok(document.querySelector('.config-editor-modal-overlay'), 'full-screen modal');
    assert.equal(document.querySelector('.config-editor-inplace'), null);
    assert.equal(document.getElementById('config-editor-overlay').hidden, false, 'the drawer stays under it');
});
