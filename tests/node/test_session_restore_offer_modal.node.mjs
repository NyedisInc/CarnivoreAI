import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { makeDom } from '../helpers/fake_overlay_dom.mjs';

const SRC = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js', 'session-restore-offer.js'), 'utf8');

function load() {
    const { document, overlays, body } = makeDom(['#restore-offer-done']);
    const trap = { escape: null, released: 0 };
    const sandbox = {
        console: { log() {}, warn() {}, error() {} }, document, setTimeout: () => 0, Date, CSS: { escape: String },
        ModalStack: { trap: (_el, opts) => { trap.escape = opts.onEscape; return () => { trap.released += 1; }; } },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(SRC, sandbox);
    return { offer: sandbox.SessionRestoreOffer, overlays, body, trap };
}

test('render takes the modal trap, Escape declines, and closing releases the trap', () => {
    const { offer, overlays, body, trap } = load();
    const calls = [];
    const api = { call: (url, opts) => { calls.push([url, opts && opts.method]); return Promise.resolve({}); } };
    offer.render(api, { id: 'o1', reason: 'boot' }, [{ session_uuid: 'a', selectable: true }]);
    assert.equal(typeof trap.escape, 'function', 'ModalStack.trap was called with an onEscape');
    assert.equal(body.children.length, 1);
    trap.escape();
    assert.equal(calls.length, 1, 'Escape runs the decline call, like the not-now button');
    assert.match(calls[0][0], /decline$/);
    overlays[0].nodes['#restore-offer-no'].disabled = true;
    trap.escape();
    assert.equal(calls.length, 1, 'with the buttons disabled (a reopen running) Escape does nothing');
});
