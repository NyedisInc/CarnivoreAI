
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT = path.join(__dirname, '..', 'client');

let failures = 0;
let passes = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

function makeRealm(opts = {}) {
    const { withGuard = true } = opts;
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        requestAnimationFrame() {},
        setTimeout, clearTimeout, setInterval, clearInterval,
        TextEncoder, TextDecoder,
        WebSocket: { OPEN: 1, CLOSING: 2, CLOSED: 3 },
        document: {
            getElementById: () => null,
            querySelector: () => null,
            addEventListener() {},
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);

    if (withGuard) {
        vm.runInContext(
            fs.readFileSync(path.join(CLIENT, 'js', 'terminal-frame-guard.js'), 'utf8'),
            sandbox, { filename: 'terminal-frame-guard.js' }
        );
    }
    vm.runInContext(
        fs.readFileSync(path.join(CLIENT, 'js', 'terminal-client-factory.js'), 'utf8')
        + '\n'
        + fs.readFileSync(path.join(CLIENT, 'js', 'terminal.js'), 'utf8'),
        sandbox, { filename: 'terminal.js' }
    );
    return sandbox;
}

function frameIn(sandbox, text) {
    const mk = vm.runInContext('(codes) => new Uint8Array(codes).buffer', sandbox);
    return mk([...Buffer.from(text, 'utf8')]);
}

function fakeSocket() {
    return {
        readyState: 1,
        binaryType: '',
        sent: [],
        send(v) { this.sent.push(v); },
        close() { this.readyState = 3; },
    };
}

function painted(controller) {
    return Buffer.concat(controller.queue.map((u) => Buffer.from(u))).toString('utf8');
}

function attach(controller, sessionId) {
    if (controller.ws) {
        controller._intentionalClose = true;
        controller.ws.close();
        controller.ws = null;
    }
    controller.queue.length = 0;
    controller._currentSession = { id: sessionId };
    const sock = fakeSocket();
    controller.ws = sock;
    controller.setupWebSocketHandlers();
    return sock;
}

// ---------------------------------------------------------------------------

test('a frame from the session the user LEFT never reaches the one they opened', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sockA = attach(t, 'ses_aaaa');
    attach(t, 'ses_bbbb');

    sockA.onmessage({ data: frameIn(sb, 'SESSION-A-PRIVATE-TRANSCRIPT') });

    assert.equal(
        painted(t), '',
        'session A bytes were painted into session B terminal'
    );
});

test('a JSON control frame from the superseded socket is dropped too', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sockA = attach(t, 'ses_aaaa');
    attach(t, 'ses_bbbb');

    let handled = 0;
    t.handleWebSocketMessage = () => { handled += 1; };
    sockA.onmessage({ data: JSON.stringify({ type: 'log', content: 'from A' }) });

    assert.equal(handled, 0, 'a control message from session A was acted on');
});

test('NEGATIVE CONTROL: the live socket still paints', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    attach(t, 'ses_aaaa');
    const sockB = attach(t, 'ses_bbbb');
    sockB.onmessage({ data: frameIn(sb, 'SESSION-B-OUTPUT') });

    assert.equal(
        painted(t), 'SESSION-B-OUTPUT',
        'the attached session stopped painting - the guard is too strict'
    );
});

test('NEGATIVE CONTROL: a session with no id yet still paints', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    t._currentSession = null;
    const sock = fakeSocket();
    t.ws = sock;
    t.setupWebSocketHandlers();
    sock.onmessage({ data: frameIn(sb, 'LEGACY-SINGLE-SESSION') });

    assert.equal(painted(t), 'LEGACY-SINGLE-SESSION');
});

test('a socket that outlives a session swap is refused on session id alone', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sock = attach(t, 'ses_aaaa');
    t._currentSession = { id: 'ses_bbbb' };
    sock.onmessage({ data: frameIn(sb, 'STALE-SESSION-BYTES') });

    assert.equal(painted(t), '', 'bytes from the previous session were painted');
});

test('a superseded socket closing does not tear down the live one', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sockA = attach(t, 'ses_aaaa');
    const sockB = attach(t, 'ses_bbbb');

    sockA.onclose({ code: 1000 });

    assert.equal(t.ws, sockB, 'the live socket was dropped by an old close event');
});

test('detaching for good still stops the keepalive timer', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sock = attach(t, 'ses_aaaa');
    t.keepaliveInterval = setInterval(() => {}, 1e6);
    t.ws = null;
    sock.onclose({ code: 1000 });

    assert.equal(t.keepaliveInterval, null, 'the keepalive timer was leaked');
});

test('a superseded socket closing leaves the NEW session keepalive alone', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sockA = attach(t, 'ses_aaaa');
    attach(t, 'ses_bbbb');
    const timer = setInterval(() => {}, 1e6);
    t.keepaliveInterval = timer;
    sockA.onclose({ code: 1000 });

    assert.equal(t.keepaliveInterval, timer, "session B's keepalive was stopped");
    clearInterval(timer);
});

test('a superseded socket is detached after its first stray event', () => {
    const sb = makeRealm();
    const t = sb.window.TerminalController;

    const sockA = attach(t, 'ses_aaaa');
    attach(t, 'ses_bbbb');
    sockA.onmessage({ data: frameIn(sb, 'first') });

    assert.equal(sockA.onmessage, null, 'the dead socket kept its handler');
    assert.equal(sockA.onclose, null, 'the dead socket kept its close handler');
});

test('with the guard module missing, isolation still holds', () => {
    const sb = makeRealm({ withGuard: false });
    const t = sb.window.TerminalController;
    assert.equal(sb.window.TerminalFrameGuard, undefined);

    const sockA = attach(t, 'ses_aaaa');
    attach(t, 'ses_bbbb');
    sockA.onmessage({ data: frameIn(sb, 'SESSION-A-PRIVATE-TRANSCRIPT') });

    assert.equal(painted(t), '', 'foreign bytes painted when the guard was absent');
});

test('the guard rule itself names each refusal', () => {
    const sb = makeRealm();
    const G = sb.window.TerminalFrameGuard;
    const a = {}, b = {};
    const verdict = (ev) => {
        const v = G.accepts(ev);
        return `${v.ok}:${v.reason}`;
    };

    assert.equal(
        verdict({ socket: a, liveSocket: b, boundSessionId: 'x', currentSessionId: 'x' }),
        'false:superseded-socket'
    );
    assert.equal(
        verdict({ socket: a, liveSocket: a, boundSessionId: 'x', currentSessionId: 'y' }),
        'false:session-changed'
    );
    assert.equal(
        verdict({ socket: a, liveSocket: a, boundSessionId: null, currentSessionId: 'y' }),
        'true:live'
    );
    assert.equal(
        verdict({ socket: a, liveSocket: a, boundSessionId: 'x', currentSessionId: 'x' }),
        'true:live'
    );
    assert.equal(G.accepts({ socket: null, liveSocket: null }).ok, false);
});

// ---------------------------------------------------------------------------

for (const [name, fn] of queue) {
    try {
        fn();
        passes += 1;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures += 1;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}
console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
