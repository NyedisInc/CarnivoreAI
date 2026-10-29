
import assert from 'node:assert/strict';

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

function makeTree() {
    const ancestorCapture = [];
    const targetBubble = [];
    let stopped = false;

    return {
        ancestor: {
            addEventListener(type, handler, opts) {
                if (type === 'wheel' && opts && opts.capture) ancestorCapture.push(handler);
            },
            removeEventListener(type, handler, opts) {
                if (type !== 'wheel' || !opts || !opts.capture) return;
                const i = ancestorCapture.indexOf(handler);
                if (i >= 0) ancestorCapture.splice(i, 1);
            },
        },
        target: {
            addEventListener(type, handler) {
                if (type === 'wheel') targetBubble.push(handler);
            },
        },
        dispatch(ev) {
            stopped = false;
            ev.stopPropagation = () => {
                stopped = true;
            };
            ev.preventDefault = () => {
                ev.defaultPrevented = true;
            };
            for (const handler of ancestorCapture) {
                handler(ev);
                if (stopped) return;
            }
            for (const handler of targetBubble) {
                handler(ev);
                if (stopped) return;
            }
        },
    };
}

function xtermFallbackWheelListener(term, onData) {
    return function (ev) {
        if (term.buffer.hasScrollback) return;
        const lines = ev.deltaY > 0 ? 1 : -1;
        const key = lines > 0 ? '[B' : '[A';
        onData(key);
    };
}

function cellCaptureWheelListener() {
    return function (ev) {
        if (!ev || ev.deltaY === 0) return;
        ev.preventDefault();
        ev.stopPropagation();
    };
}

test('RED (pre-fix shape): no capture listener lets xterm\'s fallback send arrow keys', () => {
    const tree = makeTree();
    const term = { buffer: { hasScrollback: false } };
    const sent = [];
    tree.target.addEventListener('wheel', xtermFallbackWheelListener(term, (d) => sent.push(d)));
    tree.dispatch({ deltaY: 100, cancelable: true });
    assert.ok(sent.length > 0, 'expected the unguarded bubble fallback to emit arrow-key data');
});

test('GREEN (fixed shape): the capture listener stops the event before xterm\'s fallback runs', () => {
    const tree = makeTree();
    const term = { buffer: { hasScrollback: false } };
    const sent = [];
    tree.target.addEventListener('wheel', xtermFallbackWheelListener(term, (d) => sent.push(d)));
    tree.ancestor.addEventListener('wheel', cellCaptureWheelListener(), { capture: true });
    tree.dispatch({ deltaY: 100, cancelable: true });
    assert.equal(sent.length, 0, 'expected zero onData bytes once the capture listener is installed');
});

test('GREEN: still zero bytes even if buffer.hasScrollback later becomes true (defence in depth)', () => {
    const tree = makeTree();
    const term = { buffer: { hasScrollback: true } };
    const sent = [];
    tree.target.addEventListener('wheel', xtermFallbackWheelListener(term, (d) => sent.push(d)));
    tree.ancestor.addEventListener('wheel', cellCaptureWheelListener(), { capture: true });
    tree.dispatch({ deltaY: 100, cancelable: true });
    assert.equal(sent.length, 0);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
