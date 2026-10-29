import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const SRC = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js', 'config-editor-new-file.js'), 'utf8');

function el(value = '') {
    const handlers = {};
    return { value, disabled: false, hidden: false, textContent: '', handlers,
        addEventListener(t, f) { handlers[t] = f; }, setAttribute() {}, focus() {}, remove() {}, parentNode: null };
}

function run({ createConfigFile, confirm }) {
    const ids = { '#config-editor-new-path': el('hooks/guard.py'), '#config-editor-new-root': el('user'),
        '#config-editor-new-create': el(), '#config-editor-new-cancel': el(), '#config-editor-new-error': el() };
    const overlay = { ...el(), className: '', innerHTML: '', querySelector: (s) => ids[s] || el(), remove() {} };
    const win = { API: { createConfigFile }, App: { showConfirmModal: confirm }, ModalStack: { push() {}, pop() {} } };
    const ctx = { window: win, document: { createElement: () => overlay, body: { appendChild() {} } }, console, setTimeout: () => 0 };
    vm.runInNewContext(SRC, ctx);
    const done = win.ConfigEditorNewFile.open([{ id: 'user', label: 'user' }], null);
    return { ids, done };
}

test('a confirmation_required refusal asks, then retries once with the flag', async () => {
    const calls = [];
    const createConfigFile = async (b) => {
        calls.push(b);
        if (!b.acknowledge_executable) {
            const e = new Error('refused'); e.detail = { message: 'refused', code: 'confirmation_required', acknowledge: 'executable' }; throw e;
        }
        return { ok: true };
    };
    const { ids, done } = run({ createConfigFile, confirm: async () => true });
    await ids['#config-editor-new-create'].handlers.click();
    assert.deepEqual(JSON.parse(JSON.stringify(await done)), { root: 'user', path: 'hooks/guard.py' });
    assert.equal(calls.length, 2);
    assert.equal(calls[1].acknowledge_executable, true);
});

test('declining the confirmation creates nothing and leaves the prompt open', async () => {
    const calls = [];
    const createConfigFile = async (b) => {
        calls.push(b);
        const e = new Error('refused'); e.detail = { code: 'confirmation_required', acknowledge: 'sensitive' }; throw e;
    };
    const { ids } = run({ createConfigFile, confirm: async () => false });
    await ids['#config-editor-new-create'].handlers.click();
    assert.equal(calls.length, 1);
    assert.equal(ids['#config-editor-new-create'].disabled, false);
});
