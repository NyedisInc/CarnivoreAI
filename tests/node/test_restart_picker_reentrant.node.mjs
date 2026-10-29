import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { makeDom } from '../helpers/fake_overlay_dom.mjs';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js');

function load() {
    const { document, overlays, body } = makeDom();
    const released = [];
    const sandbox = {
        console: { log() {}, error() {}, warn() {} }, document,
        CloudeI18n: { t: (k) => k },
        ModalStack: { trap: () => { const id = released.length; released.push(false); return () => { released[id] = true; }; } },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const f of ['session-restart-options.js', 'session-restart-picker.js']) vm.runInContext(fs.readFileSync(path.join(JS, f), 'utf8'), sandbox);
    return { picker: sandbox.window.SessionRestartPicker, overlays, body, released };
}

const PREVIEW = { options: [], choices: [] };

test('opening the picker twice closes the first panel and releases its trap', async () => {
    const { picker, body, released } = load();
    const first = picker.present('a', PREVIEW, 'idle', 'restart', null, false, false, false, null);
    picker.present('a', PREVIEW, 'idle', 'restart', null, false, false, false, null);
    const settled = await Promise.race([first, new Promise((r) => setTimeout(() => r('never settled'), 200))]);
    assert.equal(settled, null, 'the first panel settles as dismissed');
    assert.equal(body.children.length, 1, 'exactly one overlay stays in the document');
    assert.deepEqual(released, [true, false], 'the first trap is released, the second stays active');
});
