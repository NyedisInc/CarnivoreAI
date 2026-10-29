// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const NAVGEN_SRC = read('client/js/navigation-generation.js');
const TERM_SRC = read('client/js/terminal.js');
const INDEX_HTML = read('client/index.html');
// The boot line is one call into client/js/terminal-client-factory.js
// now, and the register() that hands it the class is the first of the
// two lines, so it is what a loader cuts at to get the class alone.
// The boot below that line does more than construct: it refuses by
// name when the client factory did not load. A loader that wants the
// class alone has to cut above the whole boot, so terminal.js carries
// this marker line and says in place that it does not move.
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';

function makeSandbox() {
    const sandbox = {
        window: {},
        document: { getElementById: () => null },
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout, clearTimeout, Promise, TextEncoder,
        requestAnimationFrame: (fn) => { fn(); return 1; },
        WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
        CustomEvent: class CustomEvent {
            constructor(type, init) { this.type = type; this.detail = (init || {}).detail; }
        },
    };
    sandbox.window.window = sandbox.window;
    sandbox.window.document = sandbox.document;
    sandbox.window.WebSocket = sandbox.WebSocket;
    sandbox.window.CustomEvent = sandbox.CustomEvent;
    sandbox.window.dispatchEvent = () => true;
    vm.createContext(sandbox);
    vm.runInContext(NAVGEN_SRC, sandbox, { filename: 'navigation-generation.js' });
    if (!sandbox.window.NavigationGeneration) {
        throw new Error(
            'navigation-generation.js did not export itself, so every case '
            + 'below would be measuring a harness bug rather than the module');
    }
    return sandbox;
}

function deferred() {
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    return { promise, resolve };
}

function loadTerminalClass(sandbox) {
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    if (cut === -1) {
        throw new Error(
            'terminal.js no longer ends with its singleton line, so this '
            + 'loader is slicing something it does not understand');
    }
    vm.runInContext(
        TERM_SRC.slice(0, cut) + '\nwindow.__TerminalClass = Terminal;',
        sandbox, { filename: 'terminal.js' });
    return sandbox.window.__TerminalClass;
}


test('begin returns a value that is current until the next begin', () => {
    const { window: w } = makeSandbox();
    const NG = w.NavigationGeneration;
    const a = NG.begin('a');
    assert.equal(NG.isCurrent(a), true);
    const b = NG.begin('b');
    assert.equal(NG.isCurrent(b), true);
    assert.equal(NG.isCurrent(a), false,
        'a superseded token must stop being current, or the whole model is a no-op');
});

test('two navigations to the SAME target are still two generations', () => {
    const { window: w } = makeSandbox();
    const NG = w.NavigationGeneration;
    const first = NG.begin('session:same');
    NG.begin('launchpad');
    const third = NG.begin('session:same');
    assert.equal(NG.isCurrent(third), true);
    assert.equal(NG.isCurrent(first), false,
        'the first visit must not be satisfied by the third, however alike they look');
});

test('a non-number is never current, so a caller that lost its token proves nothing', () => {
    const { window: w } = makeSandbox();
    const NG = w.NavigationGeneration;
    NG.begin('a');
    for (const bad of [null, undefined, '1', {}, NaN]) {
        assert.equal(NG.isCurrent(bad), false, `${String(bad)} must not read as current`);
    }
});

test('keep() answers the same question as isCurrent and never throws', () => {
    const { window: w } = makeSandbox();
    const NG = w.NavigationGeneration;
    const a = NG.begin('a');
    assert.equal(NG.keep(a, 'work'), true);
    NG.begin('b');
    assert.equal(NG.keep(a, 'work'), false);
});

test('the module has no dependencies beyond window and console', () => {
    const bare = { window: {}, console: { log() {}, debug() {} } };
    bare.window.window = bare.window;
    vm.createContext(bare);
    vm.runInContext(NAVGEN_SRC, bare, { filename: 'navigation-generation.js' });
    assert.equal(typeof bare.window.NavigationGeneration.begin, 'function');
});



test('a scheduled connect for a superseded navigation never opens a socket', async () => {
    const sandbox = makeSandbox();
    const Klass = loadTerminalClass(sandbox);
    const P = Klass.prototype;
    const NG = sandbox.window.NavigationGeneration;

    let connects = 0;
    const self = {
        _navToken: null,
        connectWebSocket() { connects += 1; },
        _navCurrent: P._navCurrent,
    };

    const nav = NG.begin('session:a');
    self._navToken = nav;
    assert.equal(self._navCurrent('scheduled connect'), true);

    NG.begin('session:b');
    assert.equal(self._navCurrent('scheduled connect'), false,
        'the 500ms delay before a connect is a window a session switch '
        + 'lands in, and a connect fired inside it opens a socket for a '
        + 'session nobody is looking at');
    assert.equal(connects, 0);
});

test('the terminal falls back to WORKING when the module is absent', () => {
    const sandbox = makeSandbox();
    delete sandbox.window.NavigationGeneration;
    const Klass = loadTerminalClass(sandbox);
    const self = { _navToken: 12345, _navCurrent: Klass.prototype._navCurrent };
    assert.equal(self._navCurrent('anything'), true);
});


test('index.html loads the module before every consumer of it', () => {
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const at = (f) => order.indexOf(f);
    assert.ok(at('navigation-generation.js') >= 0,
        'navigation-generation.js must be in index.html or it is dead code');
    for (const consumer of ['app.js', 'router.js', 'terminal.js',
                            'toast-navigate.js',
                            'session-restart-return.js']) {
        assert.ok(at('navigation-generation.js') < at(consumer),
            `navigation-generation.js must load before ${consumer}`);
    }
});

test('every entry path declares an intent, and the two App entries only READ one', () => {
    const app = read('client/js/app.js');
    for (const fn of ['showTerminal', 'returnToExistingTerminal']) {
        const body = app.slice(app.indexOf(`async ${fn}(`));
        const head = body.slice(0, body.indexOf('\n    }\n'));
        assert.ok(/AppScreenEntry\s*\.enterTerminal\(/.test(head),
            `${fn} must enter through AppScreenEntry.enterTerminal`);
        assert.ok(!/NavigationGeneration\s*\.begin\(/.test(head),
            `${fn} must NOT begin one - see this test's comment`);
    }
    const entry = read('client/js/app-screen-entry.js');
    const entryHead = entry.slice(entry.indexOf('async function enterTerminal('));
    const readsBeforeHide = entryHead.slice(0, entryHead.indexOf('app.hideAllScreens()'));
    assert.ok(/NavigationGeneration\s*\.current\(\)/.test(readsBeforeHide),
        'enterTerminal must READ the current generation');
    assert.ok(!/NavigationGeneration\s*\.begin\(/.test(entry),
        'enterTerminal must NOT begin one - see this test\'s comment');
    for (const [file, count] of [
        ['web/src/lib/drawer/row-switch.ts', 1],
        ['client/js/session-restart-return.js', 1],
        ['client/js/toast-navigate.js', 1],
        ['client/js/router.js', 1],
    ]) {
        const hits = (read(file).match(/NavigationGeneration\s*\.begin\(/g) || []).length;
        assert.equal(hits, count,
            `${file} must declare exactly ${count} navigation intent(s)`);
    }
    for (const [file, count] of [
        ['web/src/lib/launchpad/navigation.ts', 4],
        ['web/src/lib/launchpad/create-flow.ts', 2],
    ]) {
        const hits = (read(file).match(/beginNav\(/g) || []).length;
        assert.equal(hits, count,
            `${file} must declare exactly ${count} navigation intent(s)`);
    }
});

test('EVERY session-created dispatch carries its token, or the guard is waived', () => {
    const listener = read('client/js/app.js');
    assert.match(listener, /e\.detail\.nav\s*!=\s*null/,
        'app.js reads detail.nav; if that spelling changed, every dispatcher '
        + 'below is now silently unguarded and this test is the only warning');
    for (const rel of ['web/src/lib/launchpad/navigation.ts',
                       'web/src/lib/launchpad/create-flow.ts']) {
        const src = read(rel);
        for (const m of src.matchAll(/announceSessionCreated\(([^;]*?)\);/gs)) {
            assert.ok(/\bnav\b/.test(m[1]),
                `${rel}: an announce with no navigation token: ${m[1].trim().slice(0, 80)}`);
        }
    }
    const seam = read('web/src/lib/launchpad/nav-generation.ts');
    assert.match(seam, /\{ \.\.\.detail, nav \}/,
        'withNav must spell the key `nav`, which is what app.js reads');
});

test('A BOOT PAINT IS NOT A NAVIGATION, or a cold-load deep link dies', () => {
    const app = read('client/js/app.js');
    for (const fn of ['    showLaunchpad() {', '    showAuth() {']) {
        const body = app.slice(app.indexOf(fn), app.indexOf(fn) + 1600);
        const at = body.indexOf('NavigationGeneration.begin');
        assert.ok(at > 0, `${fn.trim()} must declare a navigation`);
        assert.match(body.slice(0, at), /if \(this\.currentScreen && window\.NavigationGeneration\)/,
            `${fn.trim()} must gate that on there being a screen to replace`);
    }
});

test('a stale generation never reaches the deep-link rejection banner', () => {
    const lp = read('web/src/lib/launchpad/navigation.ts');
    const guard = lp.indexOf("keepNav(deepLinkNav, 'deep-link resolve')");
    assert.ok(guard > 0, 'openProjectByName must check the deep link is still current');
    const afterGuard = lp.slice(guard, guard + 220);
    assert.ok(!/rejectTarget/.test(afterGuard),
        'the stale branch must return, never reject the target');
});
