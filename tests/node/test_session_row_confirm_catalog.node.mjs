
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import CATALOG from '../../client/js/i18n/catalog.en.js';
import { installCatalogTr } from '../helpers/catalog-tr.mjs';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SCRIPT = path.join(ROOT, 'client', 'js', 'session-row-actions-confirm.js');

let failures = 0;
const queue = [];
const test = (name, fn) => queue.push([name, fn]);

function loadBare() {
    const calls = [];
    const context = {
        console: { log() {} },
        window: { App: { showConfirmModal: (...a) => { calls.push(a); return Promise.resolve(true); } } },
    };
    context.globalThis = context;
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(SCRIPT, 'utf8'), context, { filename: 'session-row-actions-confirm.js' });
    return { context, calls, mod: context.window.SessionRowActionsConfirm };
}

test('the copy is read at dialog time, after the string layer arrives', async () => {
    const { context, calls, mod } = loadBare();
    assert.equal(mod.CONFIRM_COPY, undefined, 'the second string table is gone');
    installCatalogTr(context);
    assert.equal(await mod.confirm('close', 'api-work'), true);
    assert.equal(calls[0][0], 'close session');
});

test('every key the script reads exists in the catalog', () => {
    const keys = ['close', 'remove'].flatMap((k) => ['title', 'message', 'primary', 'details'].map((p) => `session.confirm.${k}.${p}`))
        .concat(['session.confirm.cancel', 'session.confirm.open_in_app', 'session.confirm.attached_clients']);
    for (const k of keys) assert.ok(k in CATALOG, `${k} missing from the catalog`);
    for (const k of Object.keys(CATALOG).filter((x) => x.startsWith('session.confirm.'))) {
        assert.ok(keys.includes(k), `${k} is in the catalog but nothing reads it`);
    }
});

test('the close dialog says exactly what #1768 shipped', async () => {
    const { context, calls, mod } = loadBare();
    installCatalogTr(context);
    await mod.confirm('close', 'api-work', { openInApp: true, attachedClients: 1 });
    assert.deepEqual(calls[0], [
        'close session',
        'close "api-work"?',
        'this session is open in carnivore right now, and that terminal will disconnect. '
            + '1 tmux client is attached to it right now and will be detached. '
            + 'this cannot be undone. the running process is terminated, '
            + "the project's uploads folder is deleted with every file in it, "
            + 'including files other sessions in that folder uploaded. '
            + 'the transcript is kept and stays under ~/.claude/projects.',
        'close',
        'cancel',
        'danger',
    ]);
});

test('the remove dialog says exactly what #1768 shipped', async () => {
    const { context, calls, mod } = loadBare();
    installCatalogTr(context);
    await mod.confirm('remove', 'old-thing', { attachedClients: 3 });
    assert.deepEqual(calls[0], [
        'remove session',
        'remove "old-thing"?',
        '3 tmux clients are attached to it right now and will be detached. '
            + 'this cannot be undone. this session already exited, so no running '
            + "process is stopped, but the project's uploads folder is deleted "
            + 'with every file in it, including files other sessions in that folder '
            + 'uploaded. the leftover tmux shell is cleared and carnivore forgets the '
            + 'entry. the transcript is kept and stays under ~/.claude/projects.',
        'remove',
        'cancel',
        'danger',
    ]);
});

test('an unknown action falls back to the close copy; no context adds no preamble', async () => {
    const { context, calls, mod } = loadBare();
    installCatalogTr(context);
    await mod.confirm('bogus', 'x');
    assert.equal(calls[0][0], 'close session');
    assert.equal(mod.attachmentPreamble(null), '');
    assert.equal(mod.attachmentPreamble({ openInApp: false, attachedClients: 0 }), '');
});

for (const [name, fn] of queue) {
    try { await fn(); console.log(`ok - ${name}`); } catch (err) { failures++; console.error(`NOT OK - ${name}\n${err.stack}`); }
}
console.log(`${queue.length - failures} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
