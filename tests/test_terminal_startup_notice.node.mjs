// ----------------------------------------------------------------------
// switch.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const NOTICE_SRC = read('client/js/terminal-startup-notice.js');
const BUFFER_SRC = read('client/js/terminal-input-buffer.js');
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

function fakeCloudeWeb() {
    return {
        shown: [],
        cleared: 0,
        showTerminalStartupNotice(failed) { this.shown.push(failed); },
        clearTerminalStartupNotice() { this.cleared += 1; },
    };
}

function makeNotice(withCloudeWeb = true) {
    const sandbox = { console: { log() {}, warn() {}, debug() {}, error() {} } };
    sandbox.window = sandbox;
    const web = withCloudeWeb ? fakeCloudeWeb() : undefined;
    if (web) sandbox.window.CloudeWeb = web;
    vm.createContext(sandbox);
    vm.runInContext(NOTICE_SRC, sandbox, { filename: 'terminal-startup-notice.js' });
    if (!sandbox.window.TerminalStartupNotice) {
        throw new Error('terminal-startup-notice.js did not export itself');
    }
    return { window: sandbox.window, Notice: sandbox.window.TerminalStartupNotice, web };
}


test('failed paints: show(id, "failed") tells CloudeWeb true', () => {
    const { Notice, web } = makeNotice();
    Notice.show('ses_a1', 'failed');
    assert.deepEqual(web.shown, [true]);
    assert.equal(web.cleared, 0);
    assert.equal(Notice.sessionId(), 'ses_a1');
});

for (const outcome of ['issued', 'none', 'unknown']) {
    test(`${outcome} paints nothing: show(id, "${outcome}") tells CloudeWeb false`, () => {
        const { Notice, web } = makeNotice();
        Notice.show('ses_a1', outcome);
        assert.deepEqual(web.shown, [false],
            `'${outcome}' must never be read as a failure`);
    });
}

test('none and failed can never collapse into the same outcome', () => {
    const { Notice, web } = makeNotice();
    Notice.show('ses_a1', 'none');
    Notice.show('ses_a1', 'failed');
    assert.deepEqual(web.shown, [false, true]);
});

test('clear() hides the panel and forgets the session id', () => {
    const { Notice, web } = makeNotice();
    Notice.show('ses_a1', 'failed');
    Notice.clear();
    assert.equal(web.cleared, 1);
    assert.equal(Notice.sessionId(), null);
});

test('COMPATIBILITY GATE: with no window.CloudeWeb, neither call throws', () => {
    const { Notice } = makeNotice(false);
    assert.doesNotThrow(() => Notice.show('ses_a1', 'failed'));
    assert.doesNotThrow(() => Notice.clear());
});


test('flushOnReady (the one ready-frame consumer) shows on failed', () => {
    const sandbox = { console: { log() {}, warn() {}, debug() {}, error() {} } };
    sandbox.window = sandbox;
    const web = fakeCloudeWeb();
    sandbox.window.CloudeWeb = web;
    vm.createContext(sandbox);
    vm.runInContext(NOTICE_SRC, sandbox, { filename: 'terminal-startup-notice.js' });
    vm.runInContext(BUFFER_SRC, sandbox, { filename: 'terminal-input-buffer.js' });
    const Buf = sandbox.window.TerminalInputBuffer;

    const controller = { ws: { readyState: 1, send() {} }, _connGen: null,
        _sessionId: () => 'ses_failed' };
    Buf.flushOnReady(controller, { startup_command: 'failed' });
    assert.deepEqual(web.shown, [true]);
    assert.equal(sandbox.window.TerminalStartupNotice.sessionId(), 'ses_failed');
});

test('flushOnReady ignores none', () => {
    const sandbox = { console: { log() {}, warn() {}, debug() {}, error() {} } };
    sandbox.window = sandbox;
    const web = fakeCloudeWeb();
    sandbox.window.CloudeWeb = web;
    vm.createContext(sandbox);
    vm.runInContext(NOTICE_SRC, sandbox, { filename: 'terminal-startup-notice.js' });
    vm.runInContext(BUFFER_SRC, sandbox, { filename: 'terminal-input-buffer.js' });
    const Buf = sandbox.window.TerminalInputBuffer;

    const controller = { ws: { readyState: 1, send() {} }, _connGen: null,
        _sessionId: () => 'ses_none' };
    Buf.flushOnReady(controller, { startup_command: 'none' });
    assert.deepEqual(web.shown, [false]);
});

test('a controller with no _sessionId still reaches show(), with a null id', () => {
    const sandbox = { console: { log() {}, warn() {}, debug() {}, error() {} } };
    sandbox.window = sandbox;
    const web = fakeCloudeWeb();
    sandbox.window.CloudeWeb = web;
    vm.createContext(sandbox);
    vm.runInContext(NOTICE_SRC, sandbox, { filename: 'terminal-startup-notice.js' });
    vm.runInContext(BUFFER_SRC, sandbox, { filename: 'terminal-input-buffer.js' });
    const Buf = sandbox.window.TerminalInputBuffer;

    const controller = { ws: { readyState: 1, send() {} }, _connGen: null };
    assert.doesNotThrow(() => Buf.flushOnReady(controller, { startup_command: 'failed' }));
    assert.deepEqual(web.shown, [true]);
    assert.equal(sandbox.window.TerminalStartupNotice.sessionId(), null);
});


test('_beginConnection (the one session-switch choke point) clears the notice', () => {
    const sandbox = { console: { log() {}, warn() {} } };
    sandbox.window = sandbox;
    const web = fakeCloudeWeb();
    sandbox.window.CloudeWeb = web;
    vm.createContext(sandbox);
    vm.runInContext(NOTICE_SRC, sandbox, { filename: 'terminal-startup-notice.js' });

    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    assert.notEqual(cut, -1, 'terminal.js no longer ends with its singleton line');
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__T = Terminal;',
        sandbox, { filename: 'terminal.js' });
    const P = sandbox.window.__T.prototype;

    sandbox.window.TerminalStartupNotice.show('ses_old', 'failed');
    assert.deepEqual(web.shown, [true], 'setup: a notice is showing');

    const self = { _connGen: null, _wiring: {}, _m: P._m,
        _beginConnection: P._beginConnection };
    self._beginConnection('connectToSession');

    assert.equal(web.cleared, 1);
    assert.equal(sandbox.window.TerminalStartupNotice.sessionId(), null,
        'the switch must clear BEFORE the new session\'s own ready frame can arrive');
});

test('COMPATIBILITY GATE: _beginConnection with no notice module does not throw', () => {
    const sandbox = { console: { log() {}, warn() {} } };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__T = Terminal;',
        sandbox, { filename: 'terminal.js' });
    const P = sandbox.window.__T.prototype;
    assert.equal(sandbox.window.TerminalStartupNotice, undefined, 'setup: no module');

    const self = { _connGen: null, _wiring: {}, _m: P._m,
        _beginConnection: P._beginConnection };
    assert.doesNotThrow(() => self._beginConnection('connectToSession'));
});


test('terminal.js calls _beginConnection from BOTH session-entry paths', () => {
    const calls = (TERM_SRC.match(/this\._beginConnection\(/g) || []).length;
    assert.equal(calls, 2,
        `_beginConnection is called from ${calls} places - connectToSession and `
        + 'reconnectToExistingSession must both clear a stale notice on entry');
});

test('index.html serves the notice module, and before terminal.js', () => {
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const notice = order.indexOf('terminal-startup-notice.js');
    assert.ok(notice >= 0, 'the module must be in index.html or it is dead code');
    assert.ok(notice < order.indexOf('terminal.js'));
});

test('the catalog carries exactly the two keys this surface asks for', () => {
    const CATALOG_SRC = read('client/js/i18n/catalog.en.js');
    assert.ok(CATALOG_SRC.includes("'terminal.startup.failed':"));
    assert.ok(CATALOG_SRC.includes("'terminal.startup.dismiss':"));
    assert.match(CATALOG_SRC.match(/'terminal\.startup\.failed':\s*'([^']*)'/)[1],
        /^[a-z]/, 'UI copy is lowercase and plain');
});
