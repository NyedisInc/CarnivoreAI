// not present in
// nothing to list in
// as a duplicate

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

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

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

function makeFakeDocument() {
    function stripTags(html) {
        return String(html).replace(/<[^>]*>/g, '');
    }
    function escapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }
    function createElement(tag) {
        const el = {
            tagName: String(tag).toUpperCase(),
            style: {},
            dataset: {},
            _attrs: {},
            _text: undefined,
            _html: '',
            children: [],
            appendChild(child) {
                this.children.push(child);
                return child;
            },
            querySelector() {
                throw new Error('fake DOM: querySelector is not implemented');
            },
            addEventListener() {  },
            setAttribute(k, v) { this._attrs[k] = String(v); },
            getAttribute(k) { return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null; },
            get className() { return this._className || ''; },
            set className(v) { this._className = v; },
            get innerHTML() { return this._html; },
            set innerHTML(v) { this._html = v; this._text = undefined; this.children = []; },
            get textContent() {
                if (this._text !== undefined) return this._text;
                let out = stripTags(this._html);
                for (const c of this.children) out += c.textContent;
                return out;
            },
            set textContent(v) {
                this._text = String(v == null ? '' : v);
                this._html = escapeHtml(this._text);
                this.children = [];
            },
        };
        return el;
    }
    return { createElement };
}

function loadPanel() {
    const read = (name) => fs.readFileSync(path.join(ROOT, 'client', 'js', name), 'utf8');
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const store = new Map();
    const localStorage = {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => store.set(k, String(v)),
    };
    const context = {
        window: fakeWindow,
        console: { log() {}, warn() {} },
        document: makeFakeDocument(),
        localStorage,
    };
    vm.createContext(context);
    vm.runInContext(read('config-editor-tree-state.js'), context);
    vm.runInContext(read('session-status-ui.js'), context);
    vm.runInContext(read('config-editor-roots.js'), context);
    vm.runInContext(read('config-editor-lazy.js'), context);
    vm.runInContext(read('config-editor-filter.js'), context);
    vm.runInContext(read('config-editor-rows.js'), context);
    vm.runInContext(read('config-editor-panel.js'), context);
    fakeWindow.document = context.document;
    return { ConfigEditorPanel: fakeWindow.ConfigEditorPanel, window: fakeWindow };
}

function setup(terminalController, getTree) {
    const { ConfigEditorPanel, window: win } = loadPanel();
    win.TerminalController = terminalController;
    win.API = { getConfigFileTree: getTree };
    const treeEl = win.document.createElement('div');
    ConfigEditorPanel.treeEl = treeEl;
    return { panel: ConfigEditorPanel, treeEl, window: win };
}

const PROJECT_PATH = '/Users/sam/Development/scrolltest';

function topLevelTexts(treeEl) {
    const list = treeEl.children[0];
    return list.children.map((li) => li.textContent);
}


await test('a project with files renders the roots and file names, no bookkeeping strings', async () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 's1', working_dir: PROJECT_PATH } } };
    const getTree = async (root) => {
        if (root === 'user') return { tree: [{ name: 'CLAUDE.md', rel_path: 'CLAUDE.md', is_dir: false, children: [] }] };
        if (root === 'workdir') return { tree: [{ name: 'index.html', rel_path: 'index.html', is_dir: false, children: [] }] };
        throw new Error('unexpected root ' + root);
    };
    const { panel, treeEl, window: win } = setup(tc, getTree);
    win.ConfigEditorTreeState.setNodeCollapsed('workdir:__root__', false);
    await panel._loadTree();
    const whole = treeEl.textContent;
    assert.match(whole, /index\.html/, 'the workdir file must be visible');
    assert.match(whole, /CLAUDE\.md/, 'the user file must be visible');
    assert.doesNotMatch(whole, /not present in/, 'no removed bookkeeping string');
    assert.doesNotMatch(whole, /nothing to list in/, 'no removed bookkeeping string');
    assert.equal(topLevelTexts(treeEl).length, 2, 'exactly the two roots, no extra notice rows');
});


await test('a project with no .claude/ subdirectory under workdir renders normally', async () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 's1', working_dir: PROJECT_PATH } } };
    const getTree = async (root) => {
        if (root === 'user') return { tree: [] };
        if (root === 'workdir') return { tree: [{ name: 'index.html', rel_path: 'index.html', is_dir: false, children: [] }] };
        throw new Error('unexpected root ' + root);
    };
    const { panel, treeEl } = setup(tc, getTree);
    await panel._loadTree();
    const whole = treeEl.textContent;
    assert.doesNotMatch(whole, /project \.claude/, 'the removed "project" root must never be named');
    assert.doesNotMatch(whole, /not present/, 'no removed bookkeeping string');
    assert.equal(topLevelTexts(treeEl).length, 2, 'only user + workdir roots render - no extra notice row');
});

await test('a workdir that was read and has zero entries still renders its root row (empty is not dropped)', async () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 's1', working_dir: PROJECT_PATH } } };
    const getTree = async (root) => {
        if (root === 'user' || root === 'workdir') return { tree: [] };
        throw new Error('unexpected root ' + root);
    };
    const { panel, treeEl } = setup(tc, getTree);
    await panel._loadTree();
    assert.equal(topLevelTexts(treeEl).length, 2, 'both roots render even though both are empty');
});


await test('REGRESSION: the launcher with a stale detached session renders no project-scoped text', async () => {
    // not present in
    const tc = { sessionActive: false, _currentSession: { session: { id: 's1', working_dir: PROJECT_PATH } } };
    const getTree = async (root) => {
        if (root === 'user') return { tree: [{ name: 'CLAUDE.md', rel_path: 'CLAUDE.md', is_dir: false, children: [] }] };
        throw new Error('project/workdir must not be fetched when no session is attached, got ' + root);
    };
    const { panel, treeEl } = setup(tc, getTree);
    await panel._loadTree();
    const whole = treeEl.textContent;
    assert.doesNotMatch(whole, /scrolltest/, 'the stale project path must never appear on the launcher');
    assert.doesNotMatch(whole, /project \.claude/, 'no project-scoped root label on the launcher');
    assert.doesNotMatch(whole, /project files/, 'no project-scoped root label on the launcher');
    assert.doesNotMatch(whole, /not present in/, 'no removed bookkeeping string');
    assert.doesNotMatch(whole, /nothing to list in/, 'no removed bookkeeping string');
});

await test('the true launcher (no session ever attached) also renders no project-scoped text', async () => {
    const tc = { sessionActive: false, _currentSession: null };
    const getTree = async (root) => {
        if (root === 'user') return { tree: [] };
        throw new Error('project/workdir must not be fetched when no session is attached, got ' + root);
    };
    const { panel, treeEl } = setup(tc, getTree);
    await panel._loadTree();
    const whole = treeEl.textContent;
    assert.doesNotMatch(whole, /project \.claude/);
    assert.doesNotMatch(whole, /project files/);
});


await test('REGRESSION: an unreadable workdir root renders a distinct notice, not an empty tree', async () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 's1', working_dir: PROJECT_PATH } } };
    const getTree = async (root) => {
        if (root === 'user') return { tree: [] };
        if (root === 'workdir') {
            const err = new Error('unknown or unavailable root: workdir');
            err.status = 400;
            throw err;
        }
        throw new Error('unexpected root ' + root);
    };
    const { panel, treeEl } = setup(tc, getTree);
    await panel._loadTree();
    const whole = treeEl.textContent;
    assert.match(whole, /could not reach/, 'the vanished workdir must be named as could-not-evaluate');
    assert.match(whole, /scrolltest/, 'it must say WHERE it looked');
    assert.equal(topLevelTexts(treeEl).length, 2,
        'user root (renders normally, empty and unannounced) + the workdir error row');
});

await test('REGRESSION: an unreadable subdirectory (list_error) renders distinctly from an empty one', async () => {
    const tc = { sessionActive: true, _currentSession: { session: { id: 's1', working_dir: PROJECT_PATH } } };
    const getTree = async (root) => {
        if (root === 'user') return { tree: [] };
        if (root === 'workdir') {
            return {
                tree: [
                    { name: 'locked', rel_path: 'locked', is_dir: true, list_error: 'Permission denied', children: [] },
                    { name: 'empty-dir', rel_path: 'empty-dir', is_dir: true, children: [] },
                ],
            };
        }
        throw new Error('unexpected root ' + root);
    };
    const { panel, treeEl, window: win } = setup(tc, getTree);
    win.ConfigEditorTreeState.setNodeCollapsed('workdir:__root__', false);
    win.ConfigEditorTreeState.setNodeCollapsed('workdir:locked', false);
    await panel._loadTree();
    const workdirRootLi = treeEl.children[0].children.find((li) => li.textContent.includes('project files'));
    assert.ok(workdirRootLi, 'the workdir root must have rendered');
    const workdirChildList = workdirRootLi.children[1];
    assert.ok(workdirChildList, 'the workdir root must carry a children list');
    const lockedLi = workdirChildList.children.find((li) => li.textContent.includes('locked'));
    const emptyDirLi = workdirChildList.children.find((li) => li.textContent.includes('empty-dir'));
    assert.ok(lockedLi, 'the unreadable directory must still render as a node');
    assert.ok(emptyDirLi, 'the empty directory must still render as a normal node');
    assert.match(lockedLi.textContent, /could not list contents: Permission denied/,
        'the unreadable child must name the failure');
    assert.doesNotMatch(emptyDirLi.textContent, /could not/, 'an empty directory must never read as could-not-evaluate');
    assert.notEqual(lockedLi.textContent, emptyDirLi.textContent,
        'an unreadable directory and an empty one must render different text');
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
