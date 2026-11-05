import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const ROOT = process.env.CARN_ROOT || path.join(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const TERM_SRC = read('client/js/terminal.js');
const CUT = TERM_SRC.indexOf('// THE CLASS ENDS ABOVE.');
assert.ok(CUT > 0, 'terminal.js still ends its class above the singleton marker');

/* and the real */
function world() {
    const opened = [];
    const sandbox = {
        window: {}, document: { getElementById: () => null }, setTimeout, clearTimeout, Promise, TextEncoder,
        console: { log() {}, warn() {}, debug() {}, error() {} },
        WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
        requestAnimationFrame: (fn) => { fn(); return 1; },
    };
    sandbox.window.window = sandbox.window;
    sandbox.window.document = sandbox.document;
    sandbox.window.WebSocket = sandbox.WebSocket;
    sandbox.window.API = {
        getWebSocketURL: (id) => `ws://test/${id}`,
        openWebSocket: (id) => { const s = { id, readyState: 0 }; opened.push(s); return s; },
    };
    vm.createContext(sandbox);
    vm.runInContext(read('client/js/terminal-primary-hold.js'), sandbox);
    vm.runInContext(TERM_SRC.slice(0, CUT) + '\nwindow.__T = Terminal;', sandbox, { filename: 'terminal.js' });
    return { sandbox, P: sandbox.window.__T.prototype, opened };
}

function controller(P, id) {
    return {
        _wiring: {}, _pageChrome: {}, _host: null, _m: P._m, _chrome: P._chrome, _containerEl: P._containerEl,
        ws: null, isReconnecting: false, _currentSession: { id }, term: { cols: 80, rows: 24 }, fitAddon: { fit() {} },
        updateStatus() {}, waitForFontsAndLayout: () => Promise.resolve(), setupWebSocketHandlers() {},
        connectWebSocket: P.connectWebSocket, _sessionId: P._sessionId, _unwrapSession: P._unwrapSession,
    };
}

const { sandbox, P, opened } = world();
const hold = sandbox.window.TerminalPrimaryHold;
const self = controller(P, 'ses_a');

hold.hold(['ses_a', 'carnivore_a']);
await self.connectWebSocket();
assert.equal(opened.length, 0, 'the restored session opens no primary socket while held');

self._currentSession = { id: 'ses_b' };
await self.connectWebSocket();
assert.deepEqual(opened.map((s) => s.id), ['ses_b'], 'session B gets its socket during the hold');

hold.release();
await new Promise((r) => setTimeout(r, 0));
assert.deepEqual(opened.map((s) => s.id), ['ses_b'], 'releasing does not open the refused connect of a session no longer shown');

const w2 = world();
const c2 = controller(w2.P, 'ses_a');
w2.sandbox.window.TerminalPrimaryHold.hold(['ses_a']);
await c2.connectWebSocket();
assert.equal(w2.opened.length, 0);
w2.sandbox.window.TerminalPrimaryHold.release();
await new Promise((r) => setTimeout(r, 0));
assert.deepEqual(w2.opened.map((s) => s.id), ['ses_a'], 'release re-issues the refused connect');

{
    const w = world();
    w.sandbox.window.ThemeNavigation = { applyForSession() {} };
    w.sandbox.window.ScreenChrome = { apply() {} };
    Object.assign(w.sandbox, { setHeaderIdentity() {}, setPageTitle() {}, sessionDisplayName: () => 'x' });
    vm.runInContext(read('client/js/app-screen-entry.js'), w.sandbox);
    const ctl = controller(w.P, 'ses_a');
    ctl.waitForFontsAndLayout = () => new Promise((r) => setTimeout(r, 5));
    const el = () => ({ classList: { add() {}, remove() {} } });
    w.sandbox.document.getElementById = el;
    w.sandbox.window.TerminalController = { term: {} };
    const app = {
        currentScreen: 'launchpad', logoutBtn: el(), hideAllScreens() {}, _placeStatusLight() {}, _syncSessionUrl() {}, focusTerminal() {},
    };
    const enter = (id) => {
        ctl._currentSession = { id };
        return w.sandbox.window.AppScreenEntry.enterTerminal(app, { id, tmux_session: 'carnivore_' + id }, { id }, 'test', () => ctl.connectWebSocket());
    };
    w.sandbox.window.TerminalPrimaryHold.hold(['ses_a', 'carnivore_ses_a']);
    await enter('ses_a');
    await new Promise((r) => setTimeout(r, 20));
    assert.equal(w.opened.length, 0, 'the restore entering its own held session opens no primary socket (it would mark it read)');
    ctl.ws = null;
    await enter('ses_b');
    await new Promise((r) => setTimeout(r, 20));
    assert.deepEqual(w.opened.map((s) => s.id), ['ses_b'], 'a click on another session releases the hold and connects it');
}

{
    const w = world();
    const ctl = controller(w.P, 'ses_a');
    ctl.waitForFontsAndLayout = () => new Promise((r) => setTimeout(r, 5));
    w.sandbox.window.TerminalPrimaryHold.hold(['ses_a']);
    await ctl.connectWebSocket();
    const back = ctl.connectWebSocket();
    w.sandbox.window.TerminalPrimaryHold.release();
    await back;
    await new Promise((r) => setTimeout(r, 30));
    const leaked = w.opened.filter((sock) => sock !== ctl.ws && !sock.closed);
    assert.equal(w.opened.length, 1, 'one connect for the session opens one socket, not ' + w.opened.length);
    assert.equal(leaked.length, 0, 'no socket is left open and unreferenced');
}

const html = read('client/index.html');
assert.ok(html.indexOf('terminal-primary-hold.js') > 0 && html.indexOf('terminal-primary-hold.js') < html.indexOf('/static/js/terminal.js'),
    'index.html loads the hold before terminal.js');
console.log('ok');
