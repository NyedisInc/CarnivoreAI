import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const REPO = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

function load() {
    const shown = [];
    const el = () => ({
        className: '', style: {}, innerHTML: '', attrs: {},
        setAttribute(k, v) { this.attrs[k] = v; },
        addEventListener(type, fn) { this[`on_${type}`] = fn; },
        querySelector: () => null,
    });
    const document = {
        createElement: el,
        body: { appendChild: (n) => shown.push(n), removeChild: (n) => { const i = shown.indexOf(n); if (i >= 0) shown.splice(i, 1); } },
        documentElement: { dataset: {}, style: {} },
        addEventListener() {}, querySelector: () => null, getElementById: () => null,
    };
    const sandbox = { console: { log() {}, warn() {}, error() {} }, document, Map, Set, Promise, Array, Object, setTimeout, clearTimeout };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(REPO, 'client', 'js', 'themes', 'registry.js'), 'utf8'), sandbox, { filename: 'registry.js' });
    return { Themes: sandbox.Themes, shown };
}

const click = (overlay, action) => overlay.on_click({ target: { closest: () => ({ getAttribute: () => action }) } });

test('revoking theme A closes A\'s prompt with never and leaves B\'s prompt open', async () => {
    const { Themes, shown } = load();
    const a = Themes._showConsentModal({ id: 'a', name: 'A' });
    const b = Themes._showConsentModal({ id: 'b', name: 'B' });
    assert.equal(shown.length, 2, 'positive control: both prompts are on screen');
    const result = Themes.revokeEffects('a');
    assert.equal(result.promptCancelled, true, 'A\'s prompt can still be cancelled after B opened');
    assert.equal(await a, 'never');
    assert.equal(shown.length, 1, 'only A\'s overlay was removed');
    click(shown[0], 'always');
    assert.equal(await b, 'always', 'B kept its own answer');
});

test('B\'s answer never resolves A\'s coalesced waiters', async () => {
    const { Themes, shown } = load();
    const a1 = Themes._showConsentModal({ id: 'a', name: 'A' });
    const a2 = Themes._showConsentModal({ id: 'a', name: 'A' });
    const b = Themes._showConsentModal({ id: 'b', name: 'B' });
    assert.equal(shown.length, 2, 'the same theme coalesces onto one prompt');
    const [overlayA, overlayB] = shown;
    click(overlayB, 'once');
    assert.equal(await b, 'once');
    let aSettled = false;
    Promise.all([a1, a2]).then(() => { aSettled = true; });
    await new Promise((r) => setImmediate(r));
    assert.equal(aSettled, false, 'A is still waiting for its own click');
    click(overlayA, 'never');
    assert.deepEqual(await Promise.all([a1, a2]), ['never', 'never']);
});
