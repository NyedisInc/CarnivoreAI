// move it around like a component

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { test, after } from 'node:test';
import { JSDOM } from '../web/node_modules/jsdom/lib/api.js';
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const read = (file) => readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');

function drawerMarkup() {
    const html = read('client/index.html');
    const start = html.indexOf('<div class="modal-overlay config-editor-picker-overlay"');
    const end = html.indexOf('<!-- Auth Screen -->', start);
    assert.ok(start > 0 && end > start, 'the drawer markup is in client/index.html');
    return html.slice(start, end);
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

const openWindows = [];
after(() => { for (const w of openWindows) w.close(); });

function page(width = 1400) {
    const dom = new JSDOM(`<!doctype html><body>${drawerMarkup()}
        <div id="terminal-screen" class="screen active"><div id="terminal-container"></div></div>
        <div id="cell-a"></div><div id="cell-b"></div><div id="files-cell"></div></body>`,
    { runScripts: 'outside-only', url: 'http://localhost/' });
    const window = dom.window;
    openWindows.push(window);
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
    const ctx = dom.getInternalVMContext();
    const web = installCloudeWeb(ctx);
    const pushes = [];
    const pops = [];
    window.ModalStack = {
        push: (el) => pushes.push(el), pop: (el) => pops.push(el), depth: () => pushes.length - pops.length,
    };
    window.CloudeI18n = { t: (key) => key };
    const fits = [];
    window.TerminalLayout = { requestFit: (why) => fits.push(why) };
    const calls = [];
    window.API = {
        async getConfigFileTree(root, project, opts) {
            calls.push({ root, project, path: opts && opts.path });
            return { tree: [{ name: 'CLAUDE.md', rel_path: 'CLAUDE.md', is_dir: false, children: [] }], ignore_status: 'ok' };
        },
        async findConfigFiles() { return { tree: [], ignore_status: 'ok' }; },
        async readConfigFile() { return { content: '', size: 0 }; },
    };
    window.ModuleFamilies = { CONFIG_EDITOR: [] };
    window.ModuleLoader = { loadFamily: () => Promise.resolve() };
    for (const file of ['session-status-ui.js', 'config-editor-tree-state.js', 'config-editor-roots.js',
        'config-editor-lazy.js', 'config-editor-filter.js', 'config-editor-rows.js',
        'config-editor-modal.js', 'config-editor-panel.js', 'config-editor-loader.js']) {
        vm.runInContext(read(`client/js/${file}`), ctx);
    }
    const document = window.document;
    return { window, document, web, pushes, pops, fits, calls, panel: window.ConfigEditorPanel,
        overlay: document.getElementById('config-editor-overlay') };
}

const terminal = (dir) => ({ sessionActive: true, _currentSession: { session: { working_dir: dir } } });

test('wide, the drawer docks: the page makes room, nothing is modal, the terminal refits', async () => {
    const { window, document, web, pushes, fits, overlay } = page(1400);
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/proj'), null, document.getElementById('cell-a'));
    assert.equal(overlay.hidden, false);
    assert.equal(document.body.classList.contains('right-drawer-docked'), true, 'the page is padded for it');
    assert.equal(web.rightDrawer.docked(), true);
    assert.equal(pushes.length, 0, 'a docked drawer covers nothing, so it is not a modal');
    assert.deepEqual(fits, ['right-drawer'], 'the page terminal is told its box changed, once');
    assert.equal(document.documentElement.style.getPropertyValue('--right-dock-w'), '320px',
        'it opens compact, at the left drawer width');
    assert.ok(overlay.querySelector('.right-drawer-grip'), 'the inner edge carries a resize handle');

    await window.ConfigEditorLoader.closeDrawer();
    assert.equal(overlay.hidden, true);
    assert.equal(document.body.classList.contains('right-drawer-docked'), false);
    assert.equal(fits.length, 2, 'closing refits the terminal back');
});

test('docked, Escape inside the drawer closes it without the modal stack', async () => {
    const { window, document, overlay } = page(1400);
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/proj'));
    const field = overlay.querySelector('.config-editor-tree');
    field.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await tick();
    assert.equal(overlay.hidden, true);
    assert.equal(document.body.classList.contains('right-drawer-docked'), false);
});

test('on a phone it is the overlay it was: modal, no page padding', async () => {
    const { window, document, pushes, overlay } = page(390);
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/proj'));
    assert.equal(document.body.classList.contains('right-drawer-docked'), false);
    assert.deepEqual(pushes, [overlay], 'the phone overlay is on the modal stack for Escape and focus');
});

test('the header files button toggles: a second press closes the drawer', async () => {
    const { window, overlay } = page(1400);
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'));
    assert.equal(overlay.hidden, false);
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'));
    assert.equal(overlay.hidden, true);
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'));
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'), 'skills');
    assert.equal(overlay.hidden, false);
    assert.equal(window.ConfigEditorPanel.directory, 'skills');
});

test('the width is resizable within bounds and remembered per device', async () => {
    const { window, document, web } = page(1400);
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/proj'));
    assert.equal(web.rightDrawer.setWidth(10, true), 220, 'never narrower than a file name');
    assert.equal(web.rightDrawer.setWidth(5000, true), 720, 'never wider than the cap');
    assert.equal(web.rightDrawer.setWidth(400, true), 400);
    assert.equal(window.localStorage.getItem('carnivore.rightDrawer.width'), '400');
    assert.equal(document.documentElement.style.getPropertyValue('--right-dock-w'), '400px');
    await window.ConfigEditorLoader.closeDrawer();
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/proj'));
    assert.equal(web.rightDrawer.width(), 400, 'the next open uses the remembered width');
});

test('the drawer follows the selected terminal without taking focus', async () => {
    const { window, document, calls, panel } = page(1400);
    const a = document.getElementById('cell-a');
    const b = document.getElementById('cell-b');
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/a'), null, a);
    await tick();
    const before = calls.length;
    const focused = document.createElement('button');
    document.body.appendChild(focused);
    focused.focus();
    window.ConfigEditorLoader.retarget(terminal('/b'), b);
    await tick();
    assert.equal(document.activeElement, focused, 'the retarget moved no focus');
    assert.ok(calls.slice(before).some((c) => c.project === '/b'), 'the tree was reloaded for the new folder');
    assert.equal(panel._editorHost(), b, 'a file opened now is edited in the selected cell');
    const after = calls.length;
    window.ConfigEditorLoader.retarget(terminal('/b'), a);
    await tick();
    assert.equal(calls.length, after);
    assert.equal(panel._editorHost(), a);
});

test('the files drawer is its own body (#2011): a second toggle and closeDrawer each close it', async () => {
    const { window, overlay } = page(1400);
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'));
    assert.equal(overlay.hidden, false, 'the first toggle opens the drawer');
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'));
    assert.equal(overlay.hidden, true, 'a second toggle closes it');
    await window.ConfigEditorLoader.toggleWhenReady(null, terminal('/proj'));
    assert.equal(overlay.hidden, false);
    await window.ConfigEditorLoader.closeDrawer();
    assert.equal(overlay.hidden, true, 'closeDrawer closes an open drawer');
});

test('the right drawer stylesheet pads the page and hides the handle on a phone', () => {
    const css = read('client/css/right-drawer.css');
    assert.match(css, /body\.right-drawer-docked #terminal-screen \{\s*padding-right: var\(--right-dock-w\);/);
    assert.match(css, /body\.right-drawer-docked \.config-editor-picker-overlay \{[^}]*left: auto;[^}]*width: var\(--right-dock-w\);[^}]*background: transparent;/);
    assert.match(css, /body:not\(\.right-drawer-docked\) \.right-drawer-grip \{\s*display: none;/);
    assert.doesNotMatch(css, /transition:\s*padding/, 'the padding must not animate under a refit');
    const html = read('client/index.html');
    assert.ok(html.indexOf('right-drawer.css') > html.indexOf('terminal-carnivore.css'), 'loads after the chrome');
    assert.ok(html.indexOf('right-drawer.css') < html.indexOf('popup-focus.css'), 'popup focus stays last');
});

test('a drawer opened on a phone and widened past 700px sheds every modal mark', async () => {
    const { window, document, pops, overlay } = page(390);
    await window.ConfigEditorLoader.openWhenReady(null, terminal('/proj'));
    overlay.style.zIndex = '9990';
    overlay.setAttribute('inert', '');
    overlay.setAttribute('aria-hidden', 'true');
    overlay.classList.add('modal-stack--covered');
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1400 });
    window.dispatchEvent(new window.Event('resize'));
    assert.equal(document.body.classList.contains('right-drawer-docked'), true);
    assert.deepEqual(pops, [overlay], 'it left the modal stack');
    assert.equal(overlay.style.zIndex, '', 'the ladder z-index is gone, so the docked 1100 applies');
    assert.equal(overlay.hasAttribute('inert'), false);
    assert.equal(overlay.hasAttribute('aria-hidden'), false);
    assert.equal(overlay.classList.contains('modal-stack--covered'), false);
});

test('the drawer refit is an announced change, not an observer flap to wait out', () => {
    const src = read('client/js/terminal-resize-settle.js');
    const list = src.slice(src.indexOf('var ANNOUNCED = ['), src.indexOf('];', src.indexOf('var ANNOUNCED = [')));
    assert.match(list, /'right-drawer'/);
    assert.match(read('web/src/lib/right-drawer/dock.svelte.ts'), /requestFit\?\.\('right-drawer'\)/);
});
