
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const OWN_SRC = read('client/js/terminal-input-ownership.js');
const FACTORY_SRC = read('client/js/terminal-client-factory.js');
const TERM_SRC = read('client/js/terminal.js');

const CLASS_END = '// THE CLASS ENDS ABOVE.';

const OPEN = 1;

let passes = 0;
let failures = 0;

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

function makeWorld() {
    const sandbox = {
        window: {},
        document: { getElementById: () => null, querySelector: () => null },
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout, clearTimeout, setInterval, clearInterval,
        Promise, TextEncoder, Date, JSON, Math, Object, Array, String, Number,
        WebSocket: { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 },
    };
    sandbox.window.window = sandbox.window;
    sandbox.window.document = sandbox.document;
    sandbox.window.WebSocket = sandbox.WebSocket;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(OWN_SRC, sandbox, { filename: 'terminal-input-ownership.js' });
    vm.runInContext(FACTORY_SRC, sandbox, { filename: 'terminal-client-factory.js' });

    let owner = null;
    sandbox.window.TerminalInputFocus = {
        current: () => owner,
        permits: (id) => owner === null || owner === id,
    };

    const cut = TERM_SRC.indexOf(CLASS_END);
    if (cut === -1) throw new Error('terminal.js no longer carries its class-end marker');
    vm.runInContext(TERM_SRC.slice(0, cut) + '\nwindow.__TerminalClass = Terminal;',
        sandbox, { filename: 'terminal.js' });

    return {
        w: sandbox.window,
        Own: sandbox.window.TerminalInputOwnership,
        Klass: sandbox.window.__TerminalClass,
        setOwner: (id) => { owner = id; },
    };
}

function clientFor(world, inputOwner) {
    const sent = [];
    const client = new world.Klass({
        container: null,
        chrome: {},
        wiring: { TerminalInputBuffer: null },
        inputOwner,
    });
    client.ws = { readyState: OPEN, send: (bytes) => sent.push(bytes) };
    return { client, sent };
}


test('surfacePermits demands a positive claim, and names no slot to opt out', () => {
    const world = makeWorld();
    const { Own, setOwner } = world;

    setOwner('terminal:ses_b');
    assert.equal(Own.surfacePermits(null), true);
    assert.equal(Own.surfacePermits(''), true);

    setOwner(null);
    assert.equal(Own.surfacePermits('terminal:ses_a'), false);

    setOwner('terminal:ses_a');
    assert.equal(Own.surfacePermits('terminal:ses_a'), true);

    setOwner('terminal:ses_b');
    assert.equal(Own.surfacePermits('terminal:ses_a'), false);
});

test('the shared focus store keeps its own default-permit rule', () => {
    const world = makeWorld();
    world.setOwner(null);
    assert.equal(world.Own.ownerPermits({ owner: 'terminal:ses_a' }), true,
        'the per-ticket rule must still permit an unclaimed surface');
    assert.equal(world.Own.ownerPermits({ owner: null }), true);
});

test('a missing focus store permits, it does not silently eat input', () => {
    const world = makeWorld();
    world.setOwner('terminal:ses_b');
    delete world.w.TerminalInputFocus;
    assert.equal(world.Own.surfacePermits('terminal:ses_a'), true,
        'a load-order accident must never become a terminal that ignores typing');
});

test('an unowned surface emits nothing from a cell, mouse reports included', () => {
    const world = makeWorld();
    const { client, sent } = clientFor(world, 'terminal:ses_a');
    world.setOwner(null);
    for (let i = 0; i < 6; i++) {
        client._sendUserBytes(new TextEncoder().encode(`\x1b[<35;${i};4M`));
    }
    assert.equal(sent.length, 0, 'an unclaimed surface let a cell write');
});


test('an unfocused cell emits NOTHING, including mouse reports', () => {
    const world = makeWorld();
    const { client, sent } = clientFor(world, 'terminal:ses_a');

    world.setOwner('terminal:ses_b');
    for (let i = 0; i < 5; i++) {
        assert.equal(client._sendUserBytes(new TextEncoder().encode(`\x1b[<35;${i};4M`)), false);
    }
    assert.equal(sent.length, 0, 'an unfocused cell put bytes on its socket');
});

test('the focused cell writes, and taking focus is what changes it', () => {
    const world = makeWorld();
    const { client, sent } = clientFor(world, 'terminal:ses_a');

    world.setOwner('terminal:ses_b');
    client._sendUserBytes(new TextEncoder().encode('a'));
    assert.equal(sent.length, 0);

    world.setOwner('terminal:ses_a');
    assert.equal(client._sendUserBytes(new TextEncoder().encode('a')), true);
    assert.equal(sent.length, 1, 'the focused cell was refused its own keystroke');
});

test('a handoff from cell A to cell B loses nothing', () => {
    const world = makeWorld();
    const a = clientFor(world, 'terminal:ses_a');
    const b = clientFor(world, 'terminal:ses_b');

    world.setOwner('terminal:ses_a');
    a.client._sendUserBytes(new TextEncoder().encode('1'));
    b.client._sendUserBytes(new TextEncoder().encode('x'));

    world.setOwner('terminal:ses_b');
    a.client._sendUserBytes(new TextEncoder().encode('2'));
    b.client._sendUserBytes(new TextEncoder().encode('y'));

    assert.equal(a.sent.length, 1, 'cell A wrote while cell B had focus');
    assert.equal(b.sent.length, 1, 'cell B wrote while cell A had focus');
});

test('the page-level terminal is gated exactly as every cell is', () => {
    const world = makeWorld();
    const { client, sent } = clientFor(world, world.w.CloudeTerminal.PRIMARY_INPUT_OWNER);
    world.setOwner('terminal:ses_b');
    client._sendUserBytes(new TextEncoder().encode('\x1b[<35;4;4M'));
    assert.equal(sent.length, 0, 'the page pane still wrote into somebody else\'s session');

    world.setOwner(world.w.CloudeTerminal.PRIMARY_INPUT_OWNER);
    client._sendUserBytes(new TextEncoder().encode('a'));
    assert.equal(sent.length, 1);
});

test('a terminal on a page with no surface is unguarded, as it shipped', () => {
    const world = makeWorld();
    const { client, sent } = clientFor(world, null);
    world.setOwner('terminal:ses_b');
    assert.equal(client._sendUserBytes(new TextEncoder().encode('a')), true);
    world.setOwner(null);
    assert.equal(client._sendUserBytes(new TextEncoder().encode('b')), true);
    assert.equal(sent.length, 2);
});

test('setInputOwner is what makes the pane a cell, and unmaking it undoes the gate', () => {
    const world = makeWorld();
    const { client, sent } = clientFor(world, null);
    world.setOwner('terminal:ses_b');

    client.setInputOwner(world.w.CloudeTerminal.PRIMARY_INPUT_OWNER);
    client._sendUserBytes(new TextEncoder().encode('a'));
    assert.equal(sent.length, 0, 'a named pane wrote while another cell owned input');

    client.setInputOwner(null);
    client._sendUserBytes(new TextEncoder().encode('a'));
    assert.equal(sent.length, 1, 'clearing the slot did not restore the unguarded client');
});


test('PRIMARY_INPUT_OWNER is the same string as engine/model.ts::PRIMARY_SLOT', () => {
    const world = makeWorld();
    const mine = world.w.CloudeTerminal.PRIMARY_INPUT_OWNER;
    const model = read('web/src/opscenter/engine/model.ts');
    const m = model.match(/export const PRIMARY_SLOT = '([^']+)'/);
    assert.ok(m, 'engine/model.ts no longer declares PRIMARY_SLOT as a literal');
    assert.equal(mine, m[1]);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
