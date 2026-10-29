
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const NAVGEN_SRC = read('client/js/navigation-generation.js');
const OWN_SRC = read('client/js/terminal-input-ownership.js');
const CLIP_SRC = read('client/js/clipboard.js');
const TERM_SRC = read('client/js/terminal.js');
const INDEX_HTML = read('client/index.html');
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';

const OPEN = 1;

function makeWorld() {
    const sandbox = {
        window: {},
        document: { getElementById: () => null },
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout, clearTimeout, Promise, TextEncoder,
        navigator: {},
        WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
    };
    sandbox.window.window = sandbox.window;
    sandbox.window.document = sandbox.document;
    sandbox.window.navigator = sandbox.navigator;
    sandbox.window.WebSocket = sandbox.WebSocket;
    sandbox.window.CloudeI18n = { t: (key) => key };
    vm.createContext(sandbox);
    vm.runInContext(NAVGEN_SRC, sandbox, { filename: 'navigation-generation.js' });
    vm.runInContext(OWN_SRC, sandbox, { filename: 'terminal-input-ownership.js' });

    const uploads = [];
    sandbox.window.API = {
        uploadFile: (blob, filename) => {
            const u = { filename };
            let resolve;
            u.promise = new Promise((r) => { resolve = r; });
            u.resolve = (p) => resolve({ path: p, filename });
            uploads.push(u);
            return u.promise;
        },
    };
    vm.runInContext(CLIP_SRC, sandbox, { filename: 'clipboard.js' });
    if (!sandbox.window.ClipboardTools) {
        throw new Error(
            'clipboard.js did not export itself into the sandbox, so every '
            + 'case below would be measuring a harness bug');
    }

    const term = {
        written: [],
        pills: [],
        ws: { readyState: OPEN, send() {} },
        insertText(text) { this.written.push(text); },
        _showStatusPill(msg, kind) { this.pills.push({ msg, kind }); },
        _sessionId: () => 'ses_a',
    };
    return {
        w: sandbox.window,
        term,
        uploads,
        NG: sandbox.window.NavigationGeneration,
        Own: sandbox.window.TerminalInputOwnership,
        Clip: sandbox.window.ClipboardTools,
        sandbox,
    };
}

function loadTerminalClass(sandbox) {
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    if (cut === -1) throw new Error('terminal.js no longer ends with its singleton line');
    vm.runInContext(
        TERM_SRC.slice(0, cut) + '\nwindow.__TerminalClass = Terminal;',
        sandbox, { filename: 'terminal.js' });
    return sandbox.window.__TerminalClass;
}


test('a ticket is current until the navigation moves', () => {
    const { NG, Own } = makeWorld();
    NG.begin('session:a');
    const t = Own.claim('paste');
    assert.equal(Own.permits(t), true);
    NG.begin('session:b');
    assert.equal(Own.permits(t), false);
});

test('no ticket means no check, because that path declared it needs none', () => {
    const { NG, Own } = makeWorld();
    NG.begin('session:a');
    NG.begin('session:b');
    assert.equal(Own.permits(null), true);
    assert.equal(Own.permits(undefined), true);
});

test('a missing generation module is not a refusal', () => {
    const { w, NG, Own } = makeWorld();
    NG.begin('session:a');
    const t = Own.claim('paste');
    delete w.NavigationGeneration;
    assert.equal(Own.permits(t), true,
        'a load-order accident must not stop the terminal accepting input');
});


test('POSITIVE CONTROL: an upload that lands in its own session inserts the path', async () => {
    const { term, uploads, NG, Clip } = makeWorld();
    NG.begin('session:a');
    const ticket = { nav: NG.current(), what: 'paste' };
    const run = Clip.uploadAndInject(term, {}, 'shot.png', ticket);
    uploads[0].resolve('/tmp/shot.png');
    await run;
    assert.deepEqual(term.written, ['/tmp/shot.png '],
        'the ordinary paste must still work, or nothing below measures a guard');
});

test('THE DECISIVE CASE: an upload resolving after a session switch inserts nothing, and says so', async () => {
    const { term, uploads, NG, Own, Clip } = makeWorld();
    NG.begin('session:a');
    const ticket = Own.claim('paste');
    const run = Clip.uploadAndInject(term, {}, 'shot.png', ticket);
    NG.begin('session:b');
    uploads[0].resolve('/tmp/shot.png');
    await run;
    assert.deepEqual(term.written, [],
        'session B must receive ZERO bytes from a paste made in session A');
    const dropped = term.pills.filter((p) => /dropped, you changed sessions/.test(p.msg));
    assert.equal(dropped.length, 1,
        'and the user must be TOLD - asserting only that B got nothing would '
        + 'pass if the code had thrown on the way there');
    assert.match(dropped[0].msg, /^paste dropped/,
        'the message names what was dropped, in the words the gesture used');
});

test('the dropped upload raises no attachment card either', async () => {
    const { w, term, uploads, NG, Own, Clip } = makeWorld();
    const shown = [];
    w.AttachmentToast = { show: (t, payload) => shown.push(payload) };
    NG.begin('session:a');
    const ticket = Own.claim('paste');
    const run = Clip.uploadAndInject(term, {}, 'shot.png', ticket);
    NG.begin('session:b');
    uploads[0].resolve('/tmp/shot.png');
    await run;
    assert.deepEqual(shown, [],
        'a receipt for a file nobody attached is a card about a session '
        + 'the user is not in');
});


test('injectText refuses a stale ticket BEFORE it reports anything else', () => {
    const { term, NG, Own, Clip } = makeWorld();
    NG.begin('session:a');
    const ticket = Own.claim('paste');
    NG.begin('session:b');
    term.ws = null;
    Clip.injectText(term, 'ls -la', ticket);
    assert.deepEqual(term.written, []);
    assert.equal(term.pills.length, 1);
    assert.match(term.pills[0].msg, /dropped, you changed sessions/,
        'the true reason must win over the not-connected report');
});

test('POSITIVE CONTROL: injectText with a current ticket still writes', () => {
    const { term, NG, Own, Clip } = makeWorld();
    NG.begin('session:a');
    const ticket = Own.claim('paste');
    Clip.injectText(term, 'ls -la', ticket);
    assert.deepEqual(term.written, ['ls -la']);
});


test('Terminal#insertText is the last line of defence and honours a ticket', () => {
    const { sandbox, NG, Own } = makeWorld();
    const Klass = loadTerminalClass(sandbox);
    const sent = [];
    const self = {
        _wiring: {}, _pageChrome: {}, _host: null,
        _m: Klass.prototype._m, _chrome: Klass.prototype._chrome, _containerEl: Klass.prototype._containerEl,
        ws: { readyState: OPEN, send: (b) => sent.push(b) },
        _noteUserInputToSession() {},
        insertText: Klass.prototype.insertText,
        _sendUserBytes: Klass.prototype._sendUserBytes,
    };
    self.term = { paste: (t) => self._sendUserBytes(new TextEncoder().encode(t)) };
    NG.begin('session:a');
    const ticket = Own.claim('command');
    self.insertText('/help', ticket);
    assert.equal(sent.length, 1, 'a current ticket must write');
    NG.begin('session:b');
    self._showStatusPill = () => {};
    self.insertText('/clear', ticket);
    assert.equal(sent.length, 1,
        'a stale ticket must not reach ws.send - this is the slash command '
        + 'picked from a panel the user left open across a switch');
    self.insertText('plain text');
    assert.equal(sent.length, 2);
});

test('Terminal#insertText pastes through term.paste and logs no text (#805)', () => {
    const { sandbox, NG, Own } = makeWorld();
    const logged = [];
    sandbox.console.log = (...a) => logged.push(a.join(' '));
    sandbox.console.warn = (...a) => logged.push(a.join(' '));
    const Klass = loadTerminalClass(sandbox);
    const sent = [];
    const pasted = [];
    const self = {
        _wiring: {}, _pageChrome: {}, _host: null,
        _m: Klass.prototype._m, _chrome: Klass.prototype._chrome, _containerEl: Klass.prototype._containerEl,
        ws: { readyState: OPEN, send: (b) => sent.push(b) },
        _noteUserInputToSession() {},
        _sendUserBytes: Klass.prototype._sendUserBytes,
        insertText: Klass.prototype.insertText,
        term: { paste: (t) => pasted.push(t) },
    };
    NG.begin('session:a');
    const secret = 'echo one\necho SECRET-two';
    self.insertText(secret, Own.claim('paste'));
    assert.deepEqual(pasted, [secret], 'the text must go through term.paste, unchanged');
    assert.equal(sent.length, 0, 'insertText must not write the socket itself');
    assert.ok(!logged.some((l) => l.includes('SECRET')),
        'pasted text must never reach the console: ' + JSON.stringify(logged));
});


test('index.html loads the ownership module before terminal.js and clipboard.js', () => {
    const order = [...INDEX_HTML.matchAll(/\/static\/js\/([A-Za-z0-9._\-/]+\.js)/g)]
        .map((m) => m[1]);
    const at = (f) => order.indexOf(f);
    assert.ok(at('terminal-input-ownership.js') >= 0,
        'the module must be in index.html or it is dead code');
    for (const consumer of ['terminal.js', 'clipboard.js', 'paste-fallback.js',
                            'slash-commands.js']) {
        assert.ok(at('terminal-input-ownership.js') < at(consumer),
            `terminal-input-ownership.js must load before ${consumer}`);
    }
    assert.ok(at('navigation-generation.js') < at('terminal-input-ownership.js'),
        'and after the generation counter it reads');
});

test('every async input path claims at the gesture, and the paste stays in capture phase', () => {
    const term = read('client/js/terminal.js');
    const handler = term.slice(term.indexOf("container.addEventListener('paste'"));
    const claimAt = handler.indexOf('TerminalInputOwnership');
    const awaitAt = handler.indexOf('await this._uploadAndInjectFile');
    assert.ok(claimAt > 0 && claimAt < awaitAt,
        'the paste handler must claim ownership before it awaits the upload');
    assert.match(handler.slice(0, handler.indexOf('}, true);') + 9), /\}, true\);/,
        'and the listener stays in CAPTURE phase - it must run before '
        + "xterm's own bubble-phase paste handler");

    const clip = read('client/js/clipboard.js');
    assert.match(clip, /input\.addEventListener\('change', async \(\) => \{[\s\S]{0,400}TerminalInputOwnership\.claim/,
        'the attach-file picker must claim at its change event');
    assert.match(clip, /function pasteFromClipboard\(term, ticket\)/,
        'pasteFromClipboard must accept and honour a ticket');

    const slash = read('client/js/slash-commands.js');
    const open = slash.slice(slash.indexOf('    open() {'));
    assert.match(open.slice(0, 600), /TerminalInputOwnership\.claim/,
        'the slash panel must claim when it OPENS, because nothing closes '
        + 'it on a session switch');
});

test('the copy sheet is deliberately unguarded, and that was measured', () => {
    const copy = read('client/js/copy-output.js');
    assert.ok(!/insertText|\.ws\.send/.test(copy),
        'copy-output.js must not write into the terminal - if it starts '
        + 'to, it needs a ticket like every other input path');
});

test('the synchronous paths take no ticket, and that is stated rather than forgotten', () => {
    const term = read('client/js/terminal.js');
    for (const fn of ['sendKeyToTerminal(keyData) {', '_writeSynthetic(data) {']) {
        const body = term.slice(term.indexOf(fn), term.indexOf(fn) + 400);
        assert.ok(!/TerminalInputOwnership/.test(body),
            `${fn} must stay unguarded: there is no await between the key `
            + 'and ws.send, so a check costs a comparison and buys nothing');
    }
    const own = read('client/js/terminal-input-ownership.js');
    assert.match(own, /keyboard[\s\S]{0,200}D-pad/,
        'and the module must say WHICH paths take none and why, or the next '
        + 'reader will add a decorative check');
});



function withFocus(w, owner) {
    const state = { owner };
    w.TerminalInputFocus = {
        current: () => state.owner,
        permits: (id) => state.owner == null || state.owner === id,
    };
    return { set: (next) => { state.owner = next; } };
}

test('a ticket records which cell owned input at the gesture', () => {
    const { w, NG, Own } = makeWorld();
    withFocus(w, 'terminal:@primary');
    NG.begin('session:a');
    assert.equal(Own.claim('paste').owner, 'terminal:@primary',
        'the ticket did not pin the pane, so the check below has nothing '
        + 'to compare and the second axis is not being measured at all');
});

test('THE DECISIVE CASE: an upload landing after the user moved to another cell is dropped', () => {
    const { w, NG, Own } = makeWorld();
    const focus = withFocus(w, 'terminal:@primary');
    NG.begin('session:a');
    const t = Own.claim('paste');
    focus.set('terminal:ses_other');
    assert.equal(NG.isCurrent(t.nav), true,
        'the session axis must be UNCHANGED here, or this test would be '
        + 'passing for the old reason and proving nothing new');
    assert.equal(Own.permits(t), false);
});

test('POSITIVE CONTROL: the same upload landing in the cell it was claimed from writes', () => {
    const { w, NG, Own } = makeWorld();
    withFocus(w, 'terminal:@primary');
    NG.begin('session:a');
    const t = Own.claim('paste');
    assert.equal(Own.permits(t), true,
        'a guard that refused this would make paste, upload and the slash '
        + 'commands unusable while satisfying every "nothing was written" '
        + 'assertion perfectly');
});

test('an unstated owner on either side is never a refusal', () => {
    const { w, NG, Own } = makeWorld();
    const focus = withFocus(w, null);
    NG.begin('session:a');
    const claimedWithNoOwner = Own.claim('paste');
    focus.set('terminal:ses_other');
    assert.equal(Own.permits(claimedWithNoOwner), true,
        'a ticket that pinned no pane must not be refused by one');

    focus.set('terminal:@primary');
    const claimedWithOwner = Own.claim('paste');
    focus.set(null);
    assert.equal(Own.permits(claimedWithOwner), true,
        'focus leaving every cell is not the user moving to another one');

    delete w.TerminalInputFocus;
    assert.equal(Own.permits(claimedWithOwner), true,
        'a load-order accident must not stop the terminal accepting input');
});

test('the two axes are independent, and either one alone refuses', () => {
    const { w, NG, Own } = makeWorld();
    const focus = withFocus(w, 'terminal:@primary');
    NG.begin('session:a');
    const t = Own.claim('paste');

    NG.begin('session:b');
    assert.equal(Own.permits(t), false, 'the session axis stopped refusing');

    const { w: w2, NG: NG2, Own: Own2 } = makeWorld();
    const focus2 = withFocus(w2, 'terminal:@primary');
    NG2.begin('session:a');
    const t2 = Own2.claim('paste');
    focus2.set('terminal:ses_other');
    assert.equal(Own2.permits(t2), false, 'the pane axis stopped refusing');
    void focus;
});
