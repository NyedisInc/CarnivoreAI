import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const JS = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client', 'js');
const src = (f) => fs.readFileSync(path.join(JS, f), 'utf8');

function deferred() {
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    return { promise, resolve };
}

function loadModal(fetches) {
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        document: { createElement: () => { let t = ''; return { set textContent(v) { t = String(v); }, get innerHTML() { return t; } }; } },
        API: {
            getCommonCommands: async () => ({ commands: [], command_details: [] }),
            getSlashCommands: (dir) => fetches[dir].promise,
        },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    for (const f of ['command-description.js', 'slash-command-filter.js', 'slash-favorites.js', 'slash-commands.js']) vm.runInContext(src(f), sandbox);
    return sandbox.window.SlashCommandsModal;
}

const groupsFor = (name) => ({ groups: [{ id: name, label: name, commands: [{ command: `/${name}`, description: '' }] }] });

test('the later init decides the palette even when the earlier response lands last', async () => {
    const fetches = { A: deferred(), B: deferred() };
    const modal = loadModal(fetches);
    const a = modal.init(() => {}, 'A');
    const b = modal.init(() => {}, 'B');
    fetches.B.resolve(groupsFor('b'));
    await b;
    fetches.A.resolve(groupsFor('a'));
    await a;
    assert.deepEqual(modal.groups.map((g) => g.id), ['b']);
    assert.equal(modal.commandIndex.has('/a'), false);
});

test('an init after the modal was built repaints its command list', async () => {
    const fetches = { A: deferred(), B: deferred() };
    const modal = loadModal(fetches);
    fetches.A.resolve(groupsFor('a'));
    await modal.init(() => {}, 'A');
    const list = { innerHTML: '', querySelectorAll: () => [] };
    modal.modal = { querySelector: (sel) => (sel === '#all-commands-list' ? list : { value: '' }), querySelectorAll: () => [] };
    modal.filter = { index() {}, apply() {} };
    fetches.B.resolve(groupsFor('b'));
    await modal.init(() => {}, 'B');
    assert.match(list.innerHTML, /data-group-id="b"/);
    assert.doesNotMatch(list.innerHTML, /data-group-id="a"/);
});

test('start(B) while start(A) is pending keeps B in flight when A settles', async () => {
    const sandbox = { console: { log() {}, warn() {}, error() {} }, Promise, setTimeout };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(src('slash-commands-boot.js'), sandbox);
    const gates = { A: deferred(), B: deferred() };
    sandbox.SlashCommandsModal = { loaded: false, init: (_cb, dir) => gates[dir].promise };
    const boot = sandbox.SlashCommandsBoot;
    boot.start('A');
    boot.start('B');
    gates.A.resolve();
    await new Promise((r) => setImmediate(r));
    let st = boot.state();
    assert.equal(st.loading, true, 'B is still in flight');
    assert.equal(st.loadedFor, null, 'A is not recorded as the loaded directory');
    gates.B.resolve();
    await new Promise((r) => setImmediate(r));
    st = boot.state();
    assert.equal(st.loading, false);
    assert.equal(st.loadedFor, 'B');
});
