import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const SRC = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js', 'animation-pauser.js'), 'utf8');

test('a disconnected element is unobserved and not marked', () => {
    let cb; const unobserved = [];
    function VisibilityObserver(fn) { cb = fn; this.observe = () => {}; this.unobserve = (el) => unobserved.push(el); }
    const listeners = {};
    const document = { addEventListener: (n, f) => { listeners[n] = f; } };
    vm.runInNewContext(SRC, { VisibilityObserver, document, getComputedStyle: () => ({ animationIterationCount: 'infinite' }) });
    const attrs = [];
    const el = { nodeType: 1, isConnected: false, closest: () => null, setAttribute: (a) => attrs.push(a), removeAttribute: () => {} };
    listeners.animationstart({ target: el });
    cb([{ target: el, isIntersecting: false }]);
    assert.deepEqual(unobserved, [el]);
    assert.deepEqual(attrs, []);
});

function pauser(count) {
    let cb; const observed = []; const events = [];
    function VisibilityObserver(fn) { cb = fn; this.observe = (el) => observed.push(el); this.unobserve = () => {}; }
    const listeners = {};
    const document = { addEventListener: (n, f) => { listeners[n] = f; }, dispatchEvent: (e) => events.push(e.type) };
    vm.runInNewContext(SRC, { VisibilityObserver, document, Event: class { constructor(t) { this.type = t; } }, getComputedStyle: () => ({ animationIterationCount: count }) });
    const attrs = {};
    const el = { nodeType: 1, isConnected: true, closest: () => null, setAttribute: (a) => { attrs[a] = ''; }, removeAttribute: (a) => { delete attrs[a]; }, hasAttribute: (a) => a in attrs };
    return { listeners, observed, events, cb: () => cb, el, attrs };
}

test('an amb-join-* animation (iteration count 1) is observed; any other one-shot is not', () => {
    const p = pauser('1');
    p.listeners.animationstart({ target: p.el, animationName: 'amb-join-dialog-glow' });
    assert.deepEqual(p.observed, [p.el]);
    const q = pauser('1');
    q.listeners.animationstart({ target: q.el, animationName: 'fade-in' });
    assert.deepEqual(q.observed, []);
});

test('an observer entry for a data-amb target dispatches carnivore:amb-visibility exactly once; others do not', () => {
    const p = pauser('1');
    p.el.setAttribute('data-amb', '');
    p.cb()([{ target: p.el, isIntersecting: false }, { target: p.el, isIntersecting: true }]);
    assert.deepEqual(p.events, ['carnivore:amb-visibility']);
    const q = pauser('infinite');
    q.cb()([{ target: q.el, isIntersecting: false }]);
    assert.deepEqual(q.events, []);
});
