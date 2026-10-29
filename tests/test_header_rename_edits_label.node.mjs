
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

import { Doc, results, test } from './lib-sidebar-sessions.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');

const RICH_LABEL = 'client: acme v2.1 "prod" $rate';

const HANDLE = 'cloude_client_acme_v2_1_prod_rate';

const SID = 'sid-attached';

function harness({ label = RICH_LABEL, name = HANDLE, rendered = null } = {}) {
    const document = new Doc();
    const h1 = document.createElement('h1');
    document.body.appendChild(h1);
    const titleEl = document.createElement('span');
    titleEl.id = 'header-title-text';
    h1.appendChild(titleEl);
    const pencil = document.createElement('span');
    pencil.id = 'header-rename-pencil';
    h1.appendChild(pencil);

    const win = {
        location: { origin: 'http://test.invalid', protocol: 'http:', host: 'test.invalid' },
        API: {},
        addEventListener() {},
        dispatchEvent() {},
        CustomEvent: function CustomEvent(type, opts) {
            this.type = type;
            this.detail = opts && opts.detail;
        },
        setTimeout, clearTimeout, setInterval, clearInterval,
        matchMedia() { return { matches: false, addEventListener() {} }; },
        localStorage: { getItem() { return null; }, setItem() {}, removeItem() {} },
    };
    win.window = win;
    win.setHeaderIdentity = () => {};

    const ctx = {
        window: win,
        document,
        console: { log() {}, warn() {}, error() {}, debug() {} },
        localStorage: win.localStorage,
        Date, JSON, Math, Set, Map, Promise,
        setTimeout, clearTimeout, setInterval, clearInterval,
        AbortController,
        CustomEvent: win.CustomEvent,
        WebSocket: { OPEN: 1, CLOSED: 3 },
        requestAnimationFrame(cb) { cb(); },
        alert() {},
    };
    vm.createContext(ctx);
    for (const f of ['session-label.js', 'app.js', 'terminal-header-rename.js',
                     'terminal-client-factory.js', 'terminal.js']) {
        vm.runInContext(
            fs.readFileSync(path.join(CLIENT_JS, f), 'utf8'), ctx, { filename: f });
    }

    const display = ctx.window.sessionDisplayName({ label, name }) || '';
    titleEl.dataset.fullTitle = display;
    titleEl.textContent = rendered === null ? display : rendered;

    const sent = [];
    win.API.renameSession = (sessionId, value) => {
        sent.push({ sessionId, value });
        return Promise.resolve({});
    };

    const terminal = ctx.window.TerminalController;
    const session = { id: SID, tmux_session: name, label,
                      session: { id: SID, tmux_session: name, label } };
    terminal.sessionActive = true;
    terminal._currentSession = session;
    return { terminal, window: ctx.window, document, titleEl, sent };
}

async function edit(h, { type = null, key = 'Enter' } = {}) {
    h.terminal._enterHeaderRename();
    const input = h.document.getElementById('header-rename-input');
    assert.ok(input, 'the editor must have opened');
    if (type !== null) input.value = type;
    input.dispatchEvent('keydown', { key });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    return input;
}


await test('the editor SEEDS itself with the label the user is looking at', () => {
    const h = harness();
    h.terminal._enterHeaderRename();
    const input = h.document.getElementById('header-rename-input');
    assert.ok(input, 'the editor must have opened');
    assert.equal(input.value, RICH_LABEL);
    assert.notEqual(input.value, HANDLE);
});

await test('DECISIVE: the seed is the FULL title, not the elided text on screen', () => {
    const ELIDED = 'client: acme...$rate';
    const h = harness({ rendered: ELIDED });
    assert.equal(h.titleEl.textContent, ELIDED, 'the fixture must model an elided span');
    h.terminal._enterHeaderRename();
    const input = h.document.getElementById('header-rename-input');
    assert.equal(input.value, RICH_LABEL);
    assert.ok(!input.value.includes('...'), 'an elided display value must never become the seed');
});

await test('the editor accepts the LABEL length, not the tmux name length', () => {
    const h = harness();
    h.terminal._enterHeaderRename();
    const input = h.document.getElementById('header-rename-input');
    assert.equal(
        String(input.getAttribute('maxlength') ?? input.maxLength),
        String(h.window.SessionLabel.LABEL_MAX_CHARS));
    assert.equal(String(input.getAttribute('maxlength') ?? input.maxLength), '200');
});


await test('DECISIVE: renaming a session that HAS a label stores the new label', async () => {
    const h = harness();
    await edit(h, { type: 'Archive Sweep', key: 'Enter' });
    assert.deepEqual(h.sent.map((x) => x.value), ['Archive Sweep']);
    assert.equal(h.sent[0].sessionId, SID);
});

await test('DECISIVE: the SEED is the label, so an edit builds on the label', async () => {
    const h = harness({ label: 'Archive_Sweep', name: 'cloude_Archive_Sweep' });
    h.terminal._enterHeaderRename();
    const input = h.document.getElementById('header-rename-input');
    input.value = `${input.value}_v2`;
    input.dispatchEvent('keydown', { key: 'Enter' });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();

    assert.deepEqual(h.sent.map((x) => x.value), ['Archive_Sweep_v2']);
    assert.ok(!h.sent[0].value.startsWith('cloude_'),
        'a tmux handle must never become the base of a stored label');
});

await test('DECISIVE: opening the editor and dismissing it UNCHANGED writes nothing', async () => {
    const h = harness();
    await edit(h, { type: null, key: 'Enter' });
    assert.deepEqual(h.sent, [], 'an unchanged submit must not write');
});

await test('Escape on a labelled session writes nothing either', async () => {
    const h = harness();
    await edit(h, { type: 'typed then abandoned', key: 'Escape' });
    assert.deepEqual(h.sent, []);
});

await test('a session with NO label cannot have a handle promoted into one', async () => {
    const h = harness({ label: null });
    h.terminal._enterHeaderRename();
    const input = h.document.getElementById('header-rename-input');
    assert.equal(input.value, 'client acme v2 1 prod rate');
    input.dispatchEvent('keydown', { key: 'Enter' });
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(h.sent, []);
});

await test('a label with punctuation reaches the server INSTEAD of being refused', async () => {
    const h = harness({ label: 'old', name: 'cloude_old' });
    await edit(h, { type: RICH_LABEL, key: 'Enter' });
    assert.deepEqual(h.sent.map((x) => x.value), [RICH_LABEL]);
});

await test('an empty box is a cancel, and a control character is refused locally', async () => {
    const h = harness();
    await edit(h, { type: '   ', key: 'Enter' });
    assert.deepEqual(h.sent, [], 'blanking the box must not erase the label');

    const h2 = harness();
    const input = await edit(h2, { type: 'two\nlines', key: 'Enter' });
    assert.deepEqual(h2.sent, [], 'a control character never leaves the browser');
    assert.equal(input.value, 'two\nlines');
});


await test('terminal.js carries NO second copy of the label rule', () => {
    const src = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8')
        .split('\n')
        .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
        .join('\n');
    assert.ok(!src.includes('A-Za-z0-9_-]{1,64}'),
        'the old tmux-name regex must be gone from the rename path, not merely unused');
});

const { passes, failures } = results();
console.log(`${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
