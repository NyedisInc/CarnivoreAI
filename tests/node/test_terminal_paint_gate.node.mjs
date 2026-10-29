
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const CUT = '// THE CLASS ENDS ABOVE.';

function makeWorld() {
    const state = { painted: true };
    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error() {} },
        setTimeout, clearTimeout, Promise, TextEncoder, TextDecoder, Uint8Array,
        requestAnimationFrame: (fn) => { fn(); return 1; },
        document: { getElementById: () => null, addEventListener() {}, removeEventListener() {}, documentElement: {} },
    };
    sandbox.window = sandbox;
    sandbox.window.TerminalAddons = { isPainted: () => state.painted };
    vm.createContext(sandbox);
    vm.runInContext(read('client/js/terminal-write-queue.js'), sandbox);
    vm.runInContext(read('client/js/terminal-paint-gate.js'), sandbox);
    const src = read('client/js/terminal.js');
    vm.runInContext(src.slice(0, src.indexOf(CUT)) + '\nwindow.__T = Terminal;', sandbox);
    return { sandbox, P: sandbox.__T.prototype, state };
}

function makeController(world) {
    const { P } = world;
    const term = {
        element: {}, rows: 24, written: [], refreshes: 0,
        write(data, cb) { if (data.length) this.written.push(data); if (cb) cb(); },
        refresh() { this.refreshes += 1; },
        scrollToBottom() {},
    };
    return {
        _wiring: {}, _m: P._m, term, queue: [], flushing: false, _queuedBytes: 0,
        _writeInFlight: false, _writeDrained: null, autoScrollEnabled: true,
        enqueue: P.enqueue, flush: P.flush,
    };
}

const chunk = (n, fill) => new Uint8Array(n).fill(fill);
const flat = (list) => list.flatMap((u) => [...u]);

test('hidden terminal never calls term.write; shown flushes everything in order, redraws once', () => {
    const world = makeWorld();
    const ctl = makeController(world);
    const gate = world.sandbox.TerminalPaintGate;
    gate.register(ctl);

    ctl.enqueue(chunk(3, 1));
    assert.equal(ctl.term.written.length, 1, 'POSITIVE CONTROL: a painted terminal writes at once');

    world.state.painted = false;
    gate.check();
    for (let i = 2; i <= 6; i++) ctl.enqueue(chunk(3, i));
    assert.equal(ctl.term.written.length, 1, 'no term.write while hidden');
    assert.equal(ctl.queue.length, 5, 'bytes are held in the queue');

    world.state.painted = true;
    gate.check();
    assert.deepEqual(flat(ctl.term.written.slice(1)),
        [2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5, 6, 6, 6], 'all held bytes, in order');
    assert.equal(ctl.queue.length, 0);
    assert.equal(ctl.term.refreshes, 1, 'one redraw after the flush');
});

test('held output respects the 4 MiB cap: oldest dropped whole, marker announced', () => {
    const world = makeWorld();
    const ctl = makeController(world);
    const gate = world.sandbox.TerminalPaintGate;
    const cap = world.sandbox.TerminalWriteQueue.MAX_QUEUED_BYTES;
    gate.register(ctl);
    world.state.painted = false;
    gate.check();

    const size = 1024 * 1024;
    for (let i = 1; i <= 6; i++) ctl.enqueue(chunk(size, i));
    assert.equal(ctl.term.written.length, 0);
    assert.ok(ctl._queuedBytes <= cap, 'queue stays within the cap while hidden');

    world.state.painted = true;
    gate.check();
    const out = ctl.term.written;
    assert.match(new TextDecoder().decode(out[0].slice(0, 80)), /cloude: /, 'drop is announced first');
    assert.equal(out[0][out[0].length - 1] === 6 || out[0].includes(6), true, 'newest chunk survives');
    assert.equal(out[0].includes(1), false, 'oldest chunk was shed');
});

test('a held terminal tells the server to pause, painted again it resumes, and a reconnect reasserts the pause', () => {
    const world = makeWorld();
    const ctl = makeController(world);
    const sent = [];
    ctl.ws = { readyState: 1, send: (m) => sent.push(JSON.parse(m).type) };
    const gate = world.sandbox.TerminalPaintGate;
    gate.register(ctl);
    world.state.painted = false;
    gate.check();
    gate.check();
    assert.deepEqual(sent, ['pause'], 'one pause however many checks');
    gate.reassert(ctl);
    assert.deepEqual(sent, ['pause', 'pause'], 'a reconnected socket is told again');
    world.state.painted = true;
    gate.check();
    assert.deepEqual(sent, ['pause', 'pause', 'resume']);
    gate.reassert(ctl);
    assert.equal(sent.length, 3, 'a painted terminal is not reasserted');
});
