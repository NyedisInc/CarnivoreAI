// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const TERM_SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal.js'), 'utf8');
const ABANDON_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/terminal-socket-abandon.js'), 'utf8');
// The boot line is one call into client/js/terminal-client-factory.js
// now, and the register() that hands it the class is the first of the
// two lines, so it is what a loader cuts at to get the class alone.
// The boot below that line does more than construct: it refuses by
// name when the client factory did not load. A loader that wants the
// class alone has to cut above the whole boot, so terminal.js carries
// this marker line and says in place that it does not move.
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';
const INDEX_HTML = fs.readFileSync(path.join(ROOT, 'client/index.html'), 'utf8');

const tests = [];
/** Description: register one named case. Inputs: name, fn. Output: None. */
function test(name, fn) { tests.push([name, fn]); }

const CONNECTING = 0;
const OPEN = 1;
const CLOSING = 2;
const CLOSED = 3;

function fakeSocket(readyState) {
    const sock = {
        readyState,
        closed: 0,
        handlersAtClose: null,
        onopen: () => {}, onmessage: () => {}, onerror: () => {}, onclose: () => {},
        binaryType: '',
        close() {
            this.closed += 1;
            this.handlersAtClose = {
                onopen: this.onopen,
                onmessage: this.onmessage,
                onerror: this.onerror,
                onclose: this.onclose,
            };
            this.readyState = CLOSING;
        },
    };
    return sock;
}

function loadTerminalClass(sandbox) {
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    if (cut === -1) {
        throw new Error(
            'terminal.js no longer ends with its singleton line, so this '
            + 'loader is slicing something it does not understand - refusing '
            + 'to guess');
    }
    vm.runInContext(
        TERM_SRC.slice(0, cut) + '\nwindow.__TerminalClass = Terminal;',
        sandbox, { filename: 'terminal.js' });
    return sandbox.window.__TerminalClass;
}

function makeController(existing) {
    const opened = [];
    const sandbox = {
        window: {}, document: { getElementById: () => null },
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout, clearTimeout, Promise, requestAnimationFrame: (fn) => { fn(); return 1; },
        WebSocket: { CONNECTING, OPEN, CLOSING, CLOSED },
        TextEncoder, CSS: undefined,
    };
    sandbox.window.window = sandbox.window;
    sandbox.window.document = sandbox.document;
    sandbox.window.WebSocket = sandbox.WebSocket;
    sandbox.window.API = {
        getWebSocketURL: () => 'ws://test/ws',
        openWebSocket: () => {
            const s = fakeSocket(CONNECTING);
            opened.push(s);
            return s;
        },
    };
    vm.createContext(sandbox);
    vm.runInContext(ABANDON_SRC, sandbox, { filename: 'terminal-socket-abandon.js' });
    if (!sandbox.window.TerminalSocketAbandon) {
        throw new Error(
            'terminal-socket-abandon.js did not export itself into the '
            + 'sandbox, so connectWebSocket would fall back to the old '
            + 'overwrite-and-leak path and every case below would be '
            + 'measuring the defect while looking like a harness bug');
    }
    const Klass = loadTerminalClass(sandbox);
    const P = Klass.prototype;
    for (const name of ['connectWebSocket', '_sessionId', '_unwrapSession']) {
        if (typeof P[name] !== 'function') {
            throw new Error(`terminal.js has no ${name}() any more`);
        }
    }

    const self = {
        // THE THREE ACCESSORS every method reaches its collaborators, its
        // own container and the page's chrome through, now that Terminal
        // is instantiable. On a hand-built stand-in they have to come off
        // the prototype like the methods do. Empty backing state means
        // every collaborator resolves to this sandbox's own global, which
        // is exactly what this world sets up.
        _wiring: {}, _pageChrome: {}, _host: null,
        _m: P._m, _chrome: P._chrome, _containerEl: P._containerEl,
        ws: existing,
        isReconnecting: false,
        _currentSession: { id: 'ses_test' },
        term: { cols: 80, rows: 24 },
        fitAddon: { fit() {} },
        statuses: [],
        handlersInstalled: 0,
        updateStatus(s) { this.statuses.push(s); },
        // nothing else.
        waitForFontsAndLayout() { return Promise.resolve(); },
        setupWebSocketHandlers() { this.handlersInstalled += 1; },
        connectWebSocket: P.connectWebSocket,
        _sessionId: P._sessionId,
        _unwrapSession: P._unwrapSession,
    };
    return { self, opened, sandbox };
}


test('NEGATIVE CONTROL: with no existing socket, one is opened', async () => {
    const { self, opened } = makeController(null);
    await self.connectWebSocket();
    assert.equal(opened.length, 1,
        'the control is blind: connectWebSocket must open a socket in the '
        + 'ordinary case, or every assertion below is measuring a method '
        + 'that does nothing');
    assert.equal(self.ws, opened[0], 'and it must be the one held');
    assert.equal(self.handlersInstalled, 1, 'with its handlers installed');
});

test('an OPEN socket is left alone and no second socket is opened', async () => {
    const existing = fakeSocket(OPEN);
    const { self, opened } = makeController(existing);
    await self.connectWebSocket();
    assert.equal(opened.length, 0, 'the existing connection is reused');
    assert.equal(existing.closed, 0,
        'a healthy OPEN socket must never be closed by a connect attempt');
    assert.equal(self.ws, existing, 'and it stays on the controller');
});

test('a CONNECTING socket is CLOSED, not silently abandoned', async () => {
    const existing = fakeSocket(CONNECTING);
    const { self, opened } = makeController(existing);
    await self.connectWebSocket();

    assert.equal(existing.closed, 1,
        'THIS IS THE LEAK. An abandoned CONNECTING socket that is never '
        + 'closed stays attached to the pane FIFO forever, because the '
        + 'server does not close on handshake timeout either');
    assert.equal(opened.length, 1, 'and a fresh socket takes its place');
    assert.notEqual(self.ws, existing,
        'the controller must be holding the NEW socket');
});

test('the abandoned socket has its handlers detached BEFORE it is closed', async () => {
    const existing = fakeSocket(CONNECTING);
    const { self } = makeController(existing);
    await self.connectWebSocket();

    assert.ok(existing.handlersAtClose,
        'the socket must actually have been closed for this to mean anything');
    for (const key of ['onopen', 'onmessage', 'onerror', 'onclose']) {
        assert.equal(existing.handlersAtClose[key], null,
            `${key} must already be null at the moment close() is called. A `
            + 'close we asked for is not a disconnection: reaching onclose '
            + 'would paint the disconnect banner and start a reconnect '
            + 'ladder racing the connect happening on the next line');
    }
    void self;
});

test('THE TRAP: a CONNECTING socket does not BLOCK the reconnect', async () => {
    const existing = fakeSocket(CONNECTING);
    const { self, opened } = makeController(existing);
    await self.connectWebSocket();

    assert.equal(opened.length, 1,
        'A fix that merely REFUSED while CONNECTING would pass the leak '
        + 'test above and be worse than the defect: one socket wedged in '
        + 'CONNECTING would block every future reconnect for the life of '
        + 'the page');
    assert.equal(self.handlersInstalled, 1,
        'and the replacement must be wired up, not left inert');
});

test('a CLOSING or CLOSED socket is replaced without a redundant close', async () => {
    for (const state of [CLOSING, CLOSED]) {
        const existing = fakeSocket(state);
        const { self, opened } = makeController(existing);
        await self.connectWebSocket();
        assert.equal(opened.length, 1, `a socket in state ${state} is replaced`);
        assert.equal(existing.closed, 0,
            `a socket already in state ${state} needs no close: it is not `
            + 'holding a server-side viewer open, and closing it twice is '
            + 'noise in the log for no gain');
    }
});

test('the module is actually served, and BEFORE terminal.js', () => {
    const abandon = INDEX_HTML.indexOf('terminal-socket-abandon.js');
    const terminal = INDEX_HTML.indexOf('/static/js/terminal.js');
    assert.notEqual(abandon, -1,
        'terminal-socket-abandon.js must have a script tag in index.html, '
        + 'or the fix does not ship');
    assert.notEqual(terminal, -1, 'terminal.js must still be served');
    assert.ok(abandon < terminal,
        'it must load BEFORE terminal.js, or connectWebSocket finds nothing '
        + 'on window and silently keeps leaking');
});

test('disposing during layout wait cannot open a socket or read a dead term', async () => {
    const { self, opened } = makeController(null);
    let release;
    self.waitForFontsAndLayout = () => new Promise(resolve => { release = resolve; });
    const connecting = self.connectWebSocket();
    self._disposed = true;
    self.term = null;
    release();
    await connecting;
    assert.equal(opened.length, 0);
});

test('disposing during measurement cannot open a socket', async () => {
    const { self, opened, sandbox } = makeController(null);
    sandbox.window.TerminalReadiness = { measure: async () => {
        self._disposed = true;
        self.term = null;
        return { fitted: false };
    } };
    await self.connectWebSocket();
    assert.equal(opened.length, 0);
});

test('disposing while xterm loads cannot construct a new emulator afterward', async () => {
    const { self, sandbox } = makeController(null);
    let made = 0;
    let release;
    self.waitForXterm = () => new Promise(resolve => { release = resolve; });
    self.initTerminal = () => { made++; };
    const initializing = sandbox.window.__TerminalClass.prototype.init.call(self);
    self._disposed = true;
    release();
    await initializing;
    assert.equal(made, 0);
});

// ----------------------------------------------------------------- run

let failed = 0;
for (const [name, fn] of tests) {
    try {
        await fn();
        console.log(`ok - ${name}`);
    } catch (err) {
        failed += 1;
        console.error(`not ok - ${name}\n    ${err && err.message}`);
    }
}
console.log(`\n${tests.length - failed}/${tests.length} passed`);
process.exit(failed === 0 ? 0 : 1);
