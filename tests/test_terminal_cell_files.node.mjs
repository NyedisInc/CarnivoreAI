import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test } from 'node:test';
import { JSDOM } from '../web/node_modules/jsdom/lib/api.js';

function harness() {
    const dom = new JSDOM('<div id="tree"></div>');
    const window = { TerminalController: null, ConfigEditorLazy: { FETCH_DEPTH: 1 } };
    const ctx = vm.createContext({ window, document: dom.window.document, console });
    for (const file of ['session-status-ui.js', 'config-editor-roots.js', 'config-editor-filter.js',
        'config-editor-rows.js', 'config-editor-panel.js']) {
        vm.runInContext(readFileSync(new URL(`../client/js/${file}`, import.meta.url), 'utf8'), ctx);
    }
    const panel = window.ConfigEditorPanel;
    panel._wire = () => {};
    panel.overlay = { hidden: true };
    window.ModalStack = { push() {}, pop() {} };
    panel.treeEl = dom.window.document.getElementById('tree');
    return { panel, window };
}

const client = path => ({ sessionActive: true, _currentSession: { session: { working_dir: path } } });

test('open snapshots the chosen cell, not primary or subsequent focus', async () => {
    const { panel, window } = harness();
    panel._loadTree = async () => {};
    const chosen = client('/b');
    window.TerminalController = client('/a');
    await panel.open(null, chosen, 'plugins');
    chosen._currentSession.session.working_dir = '/c';
    assert.equal(panel._currentProjectPath(), '/b');
    assert.equal(panel._directory, 'plugins');
});

test('the file explorer wears the theme of the session whose files it shows', async () => {
    const { panel, window } = harness();
    panel._loadTree = async () => {};
    const document = panel.treeEl.ownerDocument;
    panel.panel = document.createElement('div');

    const scoped = [];
    let released = 0;
    window.ThemeNavigation = {
        resolvePinnedTheme: (info) => (info && info.pinned_theme) || null,
    };
    window.Themes = {
        applyScopeTo(el, context) {
            scoped.push({ el, context });
            return () => { released += 1; };
        },
    };

    const chosen = client('/b');
    chosen._currentSession.pinned_theme = 'alien';
    await panel.open(null, chosen, 'plugins');

    assert.equal(scoped.length, 1, 'opening scopes the panel exactly once');
    assert.equal(scoped[0].el, panel.panel,
        'onto the panel, NOT the overlay: the backdrop and the chrome '
        + 'around it keep the global theme');
    assert.equal(scoped[0].context.pinnedTheme, 'alien',
        'with the pin of the session whose files are being shown');

    await panel.close();
    assert.equal(released, 1, 'closing releases the scope');

    const other = client('/c');
    await panel.open(null, other, null);
    assert.equal(scoped.length, 2);
    assert.equal(scoped[1].context.pinnedTheme, null,
        'an unpinned session carries no pin, and the registry then hands '
        + 'the panel the global theme');
});

test('THE LOADER carries the session pin into the frozen snapshot', async () => {
    const dom = new JSDOM('<div id="tree"></div>');
    const window = { ConfigEditorLazy: { FETCH_DEPTH: 1 } };
    const ctx = vm.createContext({ window, document: dom.window.document, console });
    vm.runInContext(
        readFileSync(new URL('../client/js/config-editor-loader.js', import.meta.url), 'utf8'),
        ctx,
    );

    window.ThemeNavigation = {
        resolvePinnedTheme: (info) => (info && (info.pinned_theme
            || (info.session && info.session.pinned_theme))) || null,
    };
    window.ModuleFamilies = { CONFIG_EDITOR: [] };
    window.ModuleLoader = { loadFamily: () => Promise.resolve() };

    let received = null;
    window.ConfigEditorPanel = {
        open(_trigger, target) { received = target; return Promise.resolve(); },
    };

    const controller = {
        sessionActive: true,
        _currentSession: {
            pinned_theme: 'alien',
            session: { working_dir: '/argent' },
        },
    };

    await window.ConfigEditorLoader.openWhenReady(null, controller, null);

    assert.ok(received, 'positive control: the loader must have opened the '
        + 'panel at all, or this test asserts nothing about what it passed');
    assert.equal(received._currentSession.working_dir, '/argent',
        'the folder still travels, as it always did');
    assert.equal(received._currentSession.pinned_theme, 'alien',
        'and so does the pin, or the panel cannot wear the theme of the '
        + 'session whose files it is showing');
});

test('an older tree load cannot replace a newer cell tree', async () => {
    const { panel, window } = harness();
    const releases = [];
    window.API = {
        async getConfigFileTree(_root, project) {
            if (project === '/old') await new Promise(resolve => { releases.push(resolve); });
            const name = project === '/old' ? 'old.txt' : 'new.txt';
            return { tree: [{ name, rel_path: name, is_dir: false, children: [] }] };
        },
    };
    window.ConfigEditorTreeState = {
        startsCollapsed: () => false, isForcedCollapsed: () => false, setNodeCollapsed() {},
    };
    window.ConfigEditorLazy = { FETCH_DEPTH: 1, needsFetch: () => false,
        childrenFor: async (_r, node) => ({ status: 'have', nodes: node.children || [] }) };
    panel._context = { path: '/old', reason: 'ok' };
    const old = panel._loadTree();
    panel._context = { path: '/new', reason: 'ok' };
    await panel._loadTree();
    await new Promise(resolve => setTimeout(resolve, 0));
    releases.forEach(release => release());
    await old;
    await new Promise(resolve => setTimeout(resolve, 0));
    assert.match(panel.treeEl.textContent, /new\.txt/);
    assert.doesNotMatch(panel.treeEl.textContent, /old\.txt/);
});

test('late file reads cannot repaint a newer session editor', async () => {
    const { panel, window } = harness();
    const document = panel.treeEl.ownerDocument;
    const pending = new Map();
    window.ModalStack.depth = () => 0;
    window.API = { readConfigFile: (_root, _path, project) => new Promise((_resolve, reject) => pending.set(project, reject)) };
    const ctx = vm.createContext({ window, document, console, setTimeout: () => 0 });
    vm.runInContext(readFileSync(new URL('../client/js/config-editor-modal.js', import.meta.url), 'utf8'), ctx);
    const a = window.ConfigEditorModal.open('workdir', 'a.md', false, '/a');
    await Promise.resolve();
    const b = window.ConfigEditorModal.open('workdir', 'b.md', false, '/b');
    await Promise.resolve();
    pending.get('/b')(new Error('new read'));
    await b;
    pending.get('/a')(new Error('old read'));
    await a;
    assert.match(document.getElementById('config-editor-modal-body').textContent, /new read/);
    assert.equal(document.getElementById('config-editor-modal-title').textContent, 'b.md');
});

test('first-visit lazy loading preserves the clicked cell and directory', async () => {
    let release;
    const calls = [];
    const chosen = client('/chosen');
    const window = {
        TerminalController: client('/primary'),
        ModuleFamilies: { CONFIG_EDITOR: ['editor.js'] },
        ModuleLoader: { loadFamily: () => new Promise(resolve => { release = resolve; }) },
    };
    vm.runInNewContext(readFileSync(new URL('../client/js/config-editor-loader.js', import.meta.url), 'utf8'), { window, console });
    const pending = window.ConfigEditorLoader.openWhenReady('button', chosen, 'skills');
    chosen._currentSession.session.working_dir = '/navigated';
    window.ConfigEditorPanel = { open: (...args) => calls.push(args) };
    release();
    await pending;
    assert.equal(calls.length, 1);
    assert.equal(calls[0][1]._currentSession.working_dir, '/chosen');
    assert.equal(calls[0][2], 'skills');
});

test('lazy loader surfaces a family failure rather than silently dropping the click', async () => {
    const errors = [];
    const window = {
        ModuleLoader: { loadFamily: async () => { throw new Error('offline'); } },
        Router: { showError: text => errors.push(text) },
    };
    vm.runInNewContext(readFileSync(new URL('../client/js/config-editor-loader.js', import.meta.url), 'utf8'), {
        window, console: { error() {} },
    });
    await window.ConfigEditorLoader.openWhenReady(null, client('/chosen'));
    assert.equal(errors.length, 1);
    assert.match(errors[0], /offline/);
});
