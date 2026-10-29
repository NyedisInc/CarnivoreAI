// ----------------------------------------------------------------------

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const SOLO_SRC = read('client/js/solo-window.js');
const MASTER_SRC = read('client/js/terminal-size-master.js');
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

function openWindow(search, opts = {}) {
    const calls = { getSession: [], returned: [], begin: [], panels: [], bridge: [] };
    const listeners = {};
    const root = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, hasAttribute(k) { return k in this.attrs; } };
    const state = { rows: opts.rows ?? [], records: opts.records ?? [], generation: 0, listing: [] };
    const ctx = {
        console,
        URLSearchParams,
        setTimeout,
        location: { search, origin: 'http://127.0.0.1:8000' },
        document: { documentElement: root, title: '' },
        carnivoreDesktop: opts.bridge ? {
            capabilities: ['focusSessionWindow', 'showInMain'],
            focusSessionWindow: async (id) => { calls.bridge.push(['focus', id]); return opts.focusAnswer ?? true; },
            showInMain: async (id) => { calls.bridge.push(['main', id]); return true; },
        } : undefined,
        CloudeI18n: { t: (key, params) => (params ? `${key}:${JSON.stringify(params)}` : key) },
        NavigationGeneration: {
            current: () => state.generation,
            begin: (what) => { calls.begin.push(what); return ++state.generation; },
            keep: (token) => token === state.generation,
        },
        ListingPush: {
            rows: (name) => (name === 'list' ? state.rows : name === 'records' ? state.records : null),
            onChange: (fn) => { state.listing.push(fn); return () => {}; },
        },
        API: {
            getSession: async (id) => { calls.getSession.push(id); return { session: { id }, id }; },
            listSessions: async () => state.rows,
        },
        CloudeTerminal: { SCROLLBACK_ROWS: 5000 },
        App: { returnToExistingTerminal: async (info) => { calls.returned.push(info.session.id); } },
        CloudeWeb: {
            showSoloPanel: (props) => calls.panels.push(props.kind),
            hideSoloPanel: () => calls.panels.push(null),
        },
        AppBootComplete: { announce() { calls.announced = true; } },
    };
    ctx.window = ctx;
    ctx.addEventListener = (type, fn) => { (listeners[type] ??= []).push(fn); };
    vm.createContext(ctx);
    vm.runInContext(SOLO_SRC, ctx);
    return { ctx, calls, state, listeners, root };
}

const selfOf = (w) => vm.runInContext('window', w.ctx);

const wrapper = (rowId, sesId, extra = {}) => ({ session_row_id: rowId, session: { id: sesId, label: `name-${sesId}` }, ...extra });

test('only /?solo=<1 to 15 digits> and nothing else makes a solo window, and the marker is stamped at load', () => {
    const good = openWindow('?solo=7');
    assert.equal(good.root.attrs['data-solo'], '7');
    assert.equal(good.ctx.SoloWindow.active(), true);
    for (const bad of ['', '?solo=', '?solo=abc', '?solo=7&x=1', '?x=1', '?solo=1234567890123456', '?solo=7&solo=8', '?solo=-7']) {
        const w = openWindow(bad);
        assert.equal(w.ctx.SoloWindow.active(), false, bad);
        assert.equal('data-solo' in w.root.attrs, false, bad);
    }
});

test('two windows mint different client ids; a reload of one keeps its own', () => {
    const idOf = (store) => {
        const ctx = { console, crypto: globalThis.crypto, sessionStorage: store };
        ctx.window = ctx;
        vm.createContext(ctx);
        vm.runInContext(MASTER_SRC, ctx);
        return ctx.TerminalSizeMaster.clientId();
    };
    const store = () => { const m = new Map(); return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) }; };
    const a = store();
    const b = store();
    const idA = idOf(a);
    const idB = idOf(b);
    assert.notEqual(idA, idB);
    assert.equal(idOf(a), idA);
});

test('the boot bind reads the navigation generation, binds by ROW to the live ses_ id, and home never paints', async () => {
    const w = openWindow('?solo=7', { rows: [wrapper(3, 'ses_other'), wrapper(7, 'ses_a')] });
    const app = { showLaunchpad() { throw new Error('home must never paint in a solo window'); } };
    assert.equal(w.ctx.SoloWindow.onBoot(app), true);
    await tick(); await tick();
    assert.deepEqual(w.calls.getSession, ['ses_a']);
    assert.deepEqual(w.calls.returned, ['ses_a']);
    assert.deepEqual(w.calls.begin, [], 'a boot paint is not a navigation');
    assert.equal(w.calls.announced, true);
    assert.doesNotThrow(() => app.showLaunchpad());
    assert.match(w.ctx.document.title, /name-ses_a/);
});

test('a new ses_ id under the same row is followed as a navigation the window begins itself', async () => {
    const w = openWindow('?solo=7', { rows: [wrapper(7, 'ses_a')] });
    w.ctx.SoloWindow.onBoot({});
    await tick(); await tick();
    w.state.rows = [wrapper(7, 'ses_b')];
    w.state.listing.forEach((fn) => fn(['list']));
    await tick(); await tick();
    assert.deepEqual(w.calls.returned, ['ses_a', 'ses_b']);
    assert.equal(w.calls.begin.length, 1);
});

test('a rename moves the title and never the binding', async () => {
    const w = openWindow('?solo=7', { rows: [wrapper(7, 'ses_a')] });
    w.ctx.SoloWindow.onBoot({});
    await tick(); await tick();
    w.state.rows = [wrapper(7, 'ses_a', { session: { id: 'ses_a', label: 'renamed' } })];
    w.state.listing.forEach((fn) => fn(['list']));
    await tick(); await tick();
    assert.deepEqual(w.calls.returned, ['ses_a']);
    assert.match(w.ctx.document.title, /renamed/);
});

test('a row missing from the listing is looking, an asleep record shows asleep, and neither is ever the ended panel', async () => {
    const w = openWindow('?solo=7', { rows: [] });
    w.ctx.SoloWindow.onBoot({});
    await tick(); await tick();
    assert.equal(w.calls.panels.at(-1), 'looking');
    w.state.records = [{ id: 7, session_uuid: 'u7', asleep: true, lifecycle: 'stopped', agent_type: 'claude' }];
    w.state.listing.forEach((fn) => fn(['records']));
    await tick(); await tick();
    assert.equal(w.calls.panels.at(-1), 'asleep');
    assert.equal(w.calls.panels.includes('ended'), false);
    assert.deepEqual(w.calls.returned, []);
});

test('a destroy this window saw shows the ended panel, reaches no other listener, and nothing rebinds', async () => {
    const w = openWindow('?solo=7', { rows: [wrapper(7, 'ses_a')] });
    w.ctx.SoloWindow.onBoot({});
    await tick(); await tick();
    let stopped = false;
    w.listeners['session-destroyed'][0]({ stopImmediatePropagation() { stopped = true; } });
    assert.equal(stopped, true);
    assert.equal(w.calls.panels.at(-1), 'ended');
    w.state.rows = [wrapper(7, 'ses_z')];
    w.state.listing.forEach((fn) => fn(['list']));
    await tick(); await tick();
    assert.deepEqual(w.calls.returned, ['ses_a']);
});

test('a navigation to another session goes to the main window over the bridge, and the main window never reacts to a destroy', async () => {
    const solo = openWindow('?solo=7', { bridge: true });
    assert.equal(solo.ctx.SoloWindow.forwardToMain(wrapper(9, 'ses_x')), true);
    assert.deepEqual(solo.calls.bridge, [['main', '9']]);
    const main = openWindow('', { bridge: true });
    let stopped = false;
    main.listeners['session-destroyed'][0]({ stopImmediatePropagation() { stopped = true; } });
    assert.equal(stopped, false, 'the main window keeps its own destroy handling');
});

test('a drawer click on a popped-out session focuses its window (main window only); a plain browser does nothing', async () => {
    const main = openWindow('', { bridge: true, rows: [wrapper(4, 'ses_p')] });
    assert.equal(await main.ctx.SoloWindow.focusIfOpen('ses_p'), true);
    assert.deepEqual(main.calls.bridge, [['focus', '4']]);
    const none = openWindow('', { bridge: true, rows: [wrapper(4, 'ses_p')], focusAnswer: false });
    assert.equal(await none.ctx.SoloWindow.focusIfOpen('ses_p'), false);
    const browser = openWindow('', { rows: [wrapper(4, 'ses_p')] });
    assert.equal(await browser.ctx.SoloWindow.focusIfOpen('ses_p'), false);
});

test('the main window shows a row the shell asked for, held until its boot is done; a solo window and a stranger are ignored', async () => {
    const main = openWindow('', { rows: [wrapper(5, 'ses_q')] });
    const message = (extra = {}) => ({ source: selfOf(main), origin: main.ctx.location.origin, data: { type: 'carnivore.show-row', row_id: '5' }, ...extra });
    main.listeners.message[0](message());
    await tick();
    assert.deepEqual(main.calls.returned, [], 'held until the boot');
    main.ctx.SoloWindow.onBoot({});
    await tick(); await tick(); await tick();
    assert.deepEqual(main.calls.returned, ['ses_q']);
    main.listeners.message[0](message({ origin: 'http://evil.example' }));
    main.listeners.message[0](message({ source: {} }));
    main.listeners.message[0](message({ data: { type: 'carnivore.show-row', row_id: '5; drop' } }));
    await tick(); await tick();
    assert.deepEqual(main.calls.returned, ['ses_q']);
    const solo = openWindow('?solo=7', { rows: [wrapper(5, 'ses_q')] });
    solo.ctx.SoloWindow.onBoot({});
    solo.listeners.message[0]({ source: selfOf(solo), origin: solo.ctx.location.origin, data: { type: 'carnivore.show-row', row_id: '5' } });
    await tick(); await tick();
    assert.deepEqual(solo.calls.returned, [], 'a solo window never takes another session');
});
