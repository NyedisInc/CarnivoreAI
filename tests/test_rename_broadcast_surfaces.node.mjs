
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');

const TMUX_NAME = 'cloude_my-project';
const SID = 'sid-attached';

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => void} fn  Body; throwing marks it failed.
 * @returns {void}
 */
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

function makeSandbox() {
    const headerCalls = [];
    const fakeDocument = {
        title: '',
        getElementById() { return null; },
        querySelector() { return null; },
        querySelectorAll() { return []; },
        addEventListener() {},
        createElement() {
            return {
                addEventListener() {},
                classList: { add() {}, remove() {} },
                style: {},
                dataset: {},
                setAttribute() {},
                appendChild() {},
                set textContent(v) { this._t = v; },
                get textContent() { return this._t || ''; },
                get innerHTML() { return this._t || ''; },
            };
        },
    };
    const fakeWindow = {
        location: { origin: 'http://test.invalid', protocol: 'http:', host: 'test.invalid' },
        API: {},
        addEventListener() {},
        dispatchEvent() {},
        CustomEvent: function CustomEvent(type, opts) {
            this.type = type;
            this.detail = opts && opts.detail;
        },
        setTimeout, clearTimeout, setInterval, clearInterval,
        matchMedia() { return { matches: false, addEventListener() {} }; },
        localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    };
    fakeWindow.window = fakeWindow;

    const context = {
        window: fakeWindow,
        document: fakeDocument,
        console: { log() {}, warn() {}, error() {}, debug() {} },
        localStorage: fakeWindow.localStorage,
        setTimeout, clearTimeout, setInterval, clearInterval,
        AbortController,
        CustomEvent: fakeWindow.CustomEvent,
        WebSocket: { OPEN: 1, CLOSED: 3 },
        requestAnimationFrame(cb) { cb(); },
        alert() {},
    };
    vm.createContext(context);
    // terminal-header-rename.js is the page-chrome half of this
    // control, lifted out of terminal.js when the terminal became
    // instantiable: one header, however many terminals the page holds.
    for (const f of ['session-label.js', 'app.js', 'terminal-header-rename.js',
                     'terminal-client-factory.js', 'terminal.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(CLIENT_JS, f), 'utf8'), context, { filename: f });
    }
    fakeWindow.setHeaderIdentity = (opts) => { headerCalls.push(opts); };
    const terminal = context.window.TerminalController;
    const session = { id: SID, tmux_session: TMUX_NAME, session: { id: SID, tmux_session: TMUX_NAME } };
    terminal.sessionActive = true;
    terminal._currentSession = session;
    terminal._sessionId = () => SID;
    terminal._exitHeaderRename = () => {};
    return { terminal, doc: fakeDocument, headerCalls, session, context };
}

function rename(sb, label) {
    sb.terminal.handleWebSocketMessage({
        type: 'session.renamed', session_id: SID, new_name: label,
    });
}

const HAIRY = 'client: acme v2.1 "prod" $rate';

test('the browser tab title shows the new label immediately', () => {
    const sb = makeSandbox();
    rename(sb, HAIRY);
    assert.equal(sb.doc.title, `${HAIRY} - Carnivore`);
});

test('the in-page header is handed the new label, not the tmux name', () => {
    const sb = makeSandbox();
    rename(sb, HAIRY);
    const last = sb.headerCalls[sb.headerCalls.length - 1];
    assert.ok(last, 'setHeaderIdentity was never called');
    assert.equal(last.title, HAIRY);
});

test('the tmux name is NOT moved by a rename', () => {
    const sb = makeSandbox();
    rename(sb, HAIRY);
    assert.equal(sb.session.tmux_session, TMUX_NAME);
    assert.equal(sb.session.session.tmux_session, TMUX_NAME);
});

test('the new label is recorded locally so a later re-render finds it', () => {
    const sb = makeSandbox();
    rename(sb, HAIRY);
    assert.equal(sb.session.label, HAIRY);
});

test('a rename for a DIFFERENT session leaves this tab alone', () => {
    const sb = makeSandbox();
    sb.doc.title = 'untouched';
    sb.terminal.handleWebSocketMessage({
        type: 'session.renamed', session_id: 'some-other-sid', new_name: 'nope',
    });
    assert.equal(sb.doc.title, 'untouched');
    assert.equal(sb.session.tmux_session, TMUX_NAME);
    assert.equal(sb.session.label, undefined);
});

if (failures > 0) {
    console.error(`\n${failures} failed, ${passes} passed`);
    process.exit(1);
}
console.log(`\n${passes} passed`);
