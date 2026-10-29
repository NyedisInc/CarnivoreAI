
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createEnvironment } from './mini-dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;

function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function load() {
    const env = createEnvironment();
    const sandbox = {
        window: env.window,
        document: env.document,
        console: { log() {}, warn() {}, error() {} },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'dismiss-guard.js'), 'utf8');
    vm.runInContext(src, sandbox);
    return { env, DismissGuard: env.window.DismissGuard };
}

function buildModal(document) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const content = document.createElement('div');
    content.className = 'modal-content';
    const input = document.createElement('input');
    input.type = 'text';
    input.setAttribute('id', 'slash-command-filter');
    content.appendChild(input);
    overlay.appendChild(content);
    document.body.appendChild(overlay);
    return { overlay, content, input };
}

function buildHeaderTitle(document) {
    const appTitle = document.createElement('h1');
    appTitle.setAttribute('id', 'appTitle');
    const titleText = document.createElement('span');
    titleText.setAttribute('id', 'header-title-text');
    const renameInput = document.createElement('input');
    renameInput.type = 'text';
    renameInput.setAttribute('id', 'header-rename-input');
    const pencil = document.createElement('button');
    pencil.setAttribute('id', 'header-rename-pencil');
    appTitle.appendChild(titleText);
    appTitle.appendChild(renameInput);
    appTitle.appendChild(pencil);
    document.body.appendChild(appTitle);
    return { appTitle, titleText, renameInput, pencil };
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('REPRO: a bare overlay click listener fires for a click on a child input', () => {
    const { env } = load();
    const { overlay, input } = buildModal(env.document);
    let closed = 0;
    overlay.addEventListener('click', () => { closed++; });
    input.dispatchEvent('click');
    assert.equal(closed, 1, 'expected the unguarded listener to swallow it');
});

test('REPRO: a bare container click listener fires for a click on the rename input', () => {
    const { env } = load();
    const { appTitle, renameInput } = buildHeaderTitle(env.document);
    let navigated = 0;
    appTitle.addEventListener('click', () => { navigated++; });
    renameInput.dispatchEvent('click');
    assert.equal(navigated, 1, 'expected the unguarded listener to navigate away');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('overlay dismiss does NOT fire when the search input is clicked', () => {
    const { env, DismissGuard } = load();
    const { overlay, input } = buildModal(env.document);
    let closed = 0;
    DismissGuard.onOverlayDismiss(overlay, () => { closed++; });
    input.dispatchEvent('click');
    assert.equal(closed, 0);
});

test('overlay dismiss does NOT fire while typing in the search input', () => {
    const { env, DismissGuard } = load();
    const { overlay, input } = buildModal(env.document);
    let closed = 0;
    DismissGuard.onOverlayDismiss(overlay, () => { closed++; });
    input.dispatchEvent('input');
    input.dispatchEvent('keydown', { key: 'a' });
    input.dispatchEvent('click');
    assert.equal(closed, 0);
});

test('overlay dismiss does NOT fire for a click on the modal body', () => {
    const { env, DismissGuard } = load();
    const { overlay, content } = buildModal(env.document);
    let closed = 0;
    DismissGuard.onOverlayDismiss(overlay, () => { closed++; });
    content.dispatchEvent('click');
    assert.equal(closed, 0);
});

test('overlay dismiss DOES fire for a click on the scrim itself', () => {
    const { env, DismissGuard } = load();
    const { overlay } = buildModal(env.document);
    let closed = 0;
    DismissGuard.onOverlayDismiss(overlay, () => { closed++; });
    overlay.dispatchEvent('click');
    assert.equal(closed, 1, 'click-outside-to-close must still work');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('container activate does NOT fire when the rename input is clicked', () => {
    const { env, DismissGuard } = load();
    const { appTitle, renameInput } = buildHeaderTitle(env.document);
    let navigated = 0;
    DismissGuard.onContainerActivate(appTitle, () => { navigated++; });
    renameInput.dispatchEvent('click');
    assert.equal(navigated, 0);
});

test('container activate does NOT fire when the pencil button is clicked', () => {
    const { env, DismissGuard } = load();
    const { appTitle, pencil } = buildHeaderTitle(env.document);
    let navigated = 0;
    DismissGuard.onContainerActivate(appTitle, () => { navigated++; });
    pencil.dispatchEvent('click');
    assert.equal(navigated, 0);
});

test('container activate DOES fire for a click on the plain title text', () => {
    const { env, DismissGuard } = load();
    const { appTitle, titleText } = buildHeaderTitle(env.document);
    let navigated = 0;
    DismissGuard.onContainerActivate(appTitle, () => { navigated++; });
    titleText.dispatchEvent('click');
    assert.equal(navigated, 1, 'title-click-to-go-home must still work');
});

test('container activate DOES fire for a click on the container itself', () => {
    const { env, DismissGuard } = load();
    const { appTitle } = buildHeaderTitle(env.document);
    let navigated = 0;
    DismissGuard.onContainerActivate(appTitle, () => { navigated++; });
    appTitle.dispatchEvent('click');
    assert.equal(navigated, 1);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('every form control counts as interactive', () => {
    const { env, DismissGuard } = load();
    const box = env.document.createElement('div');
    env.document.body.appendChild(box);
    for (const tag of ['input', 'textarea', 'select', 'button']) {
        const el = env.document.createElement(tag);
        box.appendChild(el);
        const e = el.dispatchEvent('click');
        assert.equal(
            DismissGuard.isInteractiveTarget(e, box), true, `${tag} should be interactive`);
    }
});

test('a contenteditable region counts as interactive', () => {
    const { env, DismissGuard } = load();
    const box = env.document.createElement('div');
    const editable = env.document.createElement('div');
    editable.setAttribute('contenteditable', 'true');
    box.appendChild(editable);
    env.document.body.appendChild(box);
    const e = editable.dispatchEvent('click');
    assert.equal(DismissGuard.isInteractiveTarget(e, box), true);
});

test('data-keep-open is the manual opt-out', () => {
    const { env, DismissGuard } = load();
    const box = env.document.createElement('div');
    const custom = env.document.createElement('div');
    custom.setAttribute('data-keep-open', '');
    box.appendChild(custom);
    env.document.body.appendChild(box);
    const e = custom.dispatchEvent('click');
    assert.equal(DismissGuard.isInteractiveTarget(e, box), true);
});

test('plain text inside the container is NOT interactive', () => {
    const { env, DismissGuard } = load();
    const box = env.document.createElement('div');
    const span = env.document.createElement('span');
    box.appendChild(span);
    env.document.body.appendChild(box);
    const e = span.dispatchEvent('click');
    assert.equal(DismissGuard.isInteractiveTarget(e, box), false);
});

test('an interactive element OUTSIDE the container does not count', () => {
    const { env, DismissGuard } = load();
    const box = env.document.createElement('div');
    const outside = env.document.createElement('input');
    env.document.body.appendChild(box);
    env.document.body.appendChild(outside);
    const e = outside.dispatchEvent('click');
    assert.equal(DismissGuard.isInteractiveTarget(e, box), false);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('outside dismiss ignores clicks inside the panel', () => {
    const { env, DismissGuard } = load();
    const panel = env.document.createElement('div');
    const child = env.document.createElement('button');
    panel.appendChild(child);
    env.document.body.appendChild(panel);
    let dismissed = 0;
    DismissGuard.onOutsideDismiss(panel, () => { dismissed++; }, { isOpen: () => true });
    child.dispatchEvent('click');
    assert.equal(dismissed, 0);
});

test('outside dismiss ignores clicks on the trigger', () => {
    const { env, DismissGuard } = load();
    const panel = env.document.createElement('div');
    const trigger = env.document.createElement('button');
    env.document.body.appendChild(panel);
    env.document.body.appendChild(trigger);
    let dismissed = 0;
    DismissGuard.onOutsideDismiss(
        panel, () => { dismissed++; }, { trigger, isOpen: () => true });
    trigger.dispatchEvent('click');
    assert.equal(dismissed, 0);
});

test('outside dismiss fires for a click elsewhere on the page', () => {
    const { env, DismissGuard } = load();
    const panel = env.document.createElement('div');
    const elsewhere = env.document.createElement('div');
    env.document.body.appendChild(panel);
    env.document.body.appendChild(elsewhere);
    let dismissed = 0;
    DismissGuard.onOutsideDismiss(panel, () => { dismissed++; }, { isOpen: () => true });
    elsewhere.dispatchEvent('click');
    assert.equal(dismissed, 1);
});

test('outside dismiss stays quiet while closed', () => {
    const { env, DismissGuard } = load();
    const panel = env.document.createElement('div');
    const elsewhere = env.document.createElement('div');
    env.document.body.appendChild(panel);
    env.document.body.appendChild(elsewhere);
    let dismissed = 0;
    DismissGuard.onOutsideDismiss(panel, () => { dismissed++; }, { isOpen: () => false });
    elsewhere.dispatchEvent('click');
    assert.equal(dismissed, 0);
});

test('outside dismiss unsubscribes', () => {
    const { env, DismissGuard } = load();
    const panel = env.document.createElement('div');
    const elsewhere = env.document.createElement('div');
    env.document.body.appendChild(panel);
    env.document.body.appendChild(elsewhere);
    let dismissed = 0;
    const off = DismissGuard.onOutsideDismiss(
        panel, () => { dismissed++; }, { isOpen: () => true });
    off();
    elsewhere.dispatchEvent('click');
    assert.equal(dismissed, 0);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('no client module wires a bare overlay-click-to-close any more', () => {
    const jsDir = path.join(__dirname, '..', 'client', 'js');
    const offenders = [];
    for (const name of fs.readdirSync(jsDir)) {
        if (!name.endsWith('.js')) continue;
        const src = fs.readFileSync(path.join(jsDir, name), 'utf8');
        const re = /overlay\.addEventListener\(\s*['"]click['"]\s*,\s*\(?\s*\)?\s*=>\s*(this\.)?close\(/g;
        if (re.test(src)) offenders.push(name);
    }
    assert.deepEqual(offenders, []);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
