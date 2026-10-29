
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import test from 'node:test';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..', '..');
const ADDONS_SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal-addons.js'), 'utf8');

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function makeSandbox() {
    const doc = { visibilityState: 'visible', handlers: {},
        addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); } };
    const clock = { now: 1_000_000 };
    const addons = [];
    class FakeAddon {
        constructor() { this.disposed = 0; this.lossFns = []; addons.push(this); }
        onContextLoss(fn) { this.lossFns.push(fn); }
        dispose() { this.disposed += 1; }
        lose() { for (const fn of this.lossFns) fn(); }
    }
    const sandbox = {
        console: { log() {}, warn() {}, error() {}, debug() {} },
        setTimeout, clearTimeout,
        document: doc,
        Date: { now: () => clock.now },
        handlers: {},
        addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); },
        WebglAddon: { WebglAddon: FakeAddon },
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(ADDONS_SRC, sandbox, { filename: 'terminal-addons.js' });
    sandbox.clock = clock;
    sandbox.addons = addons;
    sandbox.events = {
        focus() { for (const fn of sandbox.handlers.focus || []) fn({}); },
        visibilitychange() { for (const fn of doc.handlers.visibilitychange || []) fn({}); },
    };
    return sandbox;
}

function fakeTerm() {
    const listeners = [];
    const element = { isConnected: true, painted: true,
        checkVisibility() { return this.painted; } };
    const term = {
        rows: 24,
        element,
        refreshes: [],
        loadAddon() {},
        onRender(fn) { listeners.push(fn); return { dispose() {} }; },
        refresh(start, end) { this.refreshes.push([start, end]); this.render(); },
        render() { for (const fn of listeners) fn({ start: 0, end: this.rows - 1 }); },
    };
    return term;
}

test('a terminal that drew behind a cover is redrawn in full once shown', async () => {
    const sb = makeSandbox();
    const term = fakeTerm();
    assert.ok(sb.TerminalAddons.loadWebgl(term), 'the addon loads');
    const wait = sb.TerminalAddons.UNPAINTED_POLL_MS;

    term.element.painted = false;
    term.render();
    term.render();
    await sleep(wait * 3);
    assert.equal(term.refreshes.length, 0, 'nothing is redrawn while still covered');

    term.element.painted = true;
    await sleep(wait * 4);
    assert.deepEqual(term.refreshes, [[0, 23]], 'ONE full redraw after it is painted again');

    await sleep(wait * 3);
    assert.equal(term.refreshes.length, 1, 'and no more');
});

test('a terminal drawn only while painted is never redrawn', async () => {
    const sb = makeSandbox();
    const term = fakeTerm();
    sb.TerminalAddons.loadWebgl(term);
    term.render();
    term.render();
    await sleep(sb.TerminalAddons.UNPAINTED_POLL_MS * 3);
    assert.equal(term.refreshes.length, 0);
});

test('a hidden browser tab is not painted; the redraw waits for it to show', async () => {
    const sb = makeSandbox();
    const term = fakeTerm();
    sb.TerminalAddons.loadWebgl(term);
    const wait = sb.TerminalAddons.UNPAINTED_POLL_MS;
    sb.document.visibilityState = 'hidden';
    term.render();
    await sleep(wait * 3);
    assert.equal(term.refreshes.length, 0);
    sb.document.visibilityState = 'visible';
    await sleep(wait * 4);
    assert.equal(term.refreshes.length, 1);
});

test('a disposed terminal stops looking and is never redrawn', async () => {
    const sb = makeSandbox();
    const term = fakeTerm();
    sb.TerminalAddons.loadWebgl(term);
    const wait = sb.TerminalAddons.UNPAINTED_POLL_MS;
    term.element.painted = false;
    term.render();
    term.element.isConnected = false;
    await sleep(wait * 3);
    term.element.painted = true;
    term.element.isConnected = true;
    await sleep(wait * 3);
    assert.equal(term.refreshes.length, 0);
});

test('isPainted falls back to computed style without checkVisibility', () => {
    const sb = makeSandbox();
    const style = { visibility: 'hidden', display: 'block' };
    const el = { isConnected: true,
        ownerDocument: { defaultView: { getComputedStyle: () => style } } };
    assert.equal(sb.TerminalAddons.isPainted(el, { visibilityState: 'visible' }), false);
    style.visibility = 'visible';
    assert.equal(sb.TerminalAddons.isPainted(el, { visibilityState: 'visible' }), true);
    assert.equal(sb.TerminalAddons.isPainted(el, { visibilityState: 'hidden' }), false);
    assert.equal(sb.TerminalAddons.isPainted(null, { visibilityState: 'visible' }), false);
});


function loadHeld(sb, term = fakeTerm()) {
    const holder = {};
    holder._webglAddon = sb.TerminalAddons.loadWebgl(term, holder);
    return { term, holder, addon: holder._webglAddon };
}

async function settle(sb, polls = 4) {
    sb.clock.now += sb.TerminalAddons.REARM_MIN_INTERVAL_MS + 1;
    await sleep(sb.TerminalAddons.UNPAINTED_POLL_MS * polls);
}

test('a hidden-then-shown pane redraws once and the cap constants are the measured ones', async () => {
    const sb = makeSandbox();
    assert.equal(sb.TerminalAddons.WEBGL_CONTEXT_CAP, 16);
    const { term } = loadHeld(sb);
    const wait = sb.TerminalAddons.UNPAINTED_POLL_MS;
    term.element.painted = false;
    term.render();
    term.element.painted = true;
    await sleep(wait * 4);
    assert.deepEqual(term.refreshes, [[0, 23]]);
});

test('a lost context is never reloaded by the loss itself; the holder drops the dead addon', async () => {
    const sb = makeSandbox();
    const { term, holder, addon } = loadHeld(sb);
    addon.lose();
    assert.equal(holder._webglAddon, null, 'the controller no longer claims webgl');
    assert.ok(addon.disposed >= 1, 'the lost addon is disposed');
    await settle(sb, 6);
    assert.equal(sb.addons.length, 1, 'no fresh addon from the loss alone');
    assert.equal(term.refreshes.length, 0);
});

test('an evicted pane that is painted again re-arms once a context is free', async () => {
    const sb = makeSandbox();
    const { term, holder, addon } = loadHeld(sb);
    term.element.painted = false;
    addon.lose();
    term.render();
    await sleep(sb.TerminalAddons.UNPAINTED_POLL_MS * 2);
    assert.equal(sb.addons.length, 1, 'not re-armed while still covered');
    sb.clock.now += sb.TerminalAddons.REARM_MIN_INTERVAL_MS + 1;
    term.element.painted = true;
    await sleep(sb.TerminalAddons.UNPAINTED_POLL_MS * 5);
    assert.equal(sb.addons.length, 2, 'one fresh addon');
    assert.equal(holder._webglAddon, sb.addons[1], 'the holder carries the new addon');
    assert.deepEqual(term.refreshes, [[0, 23]], 'one full redraw, the covered frames included');
});

test('an evicted pane stays on the DOM renderer while 16 contexts are live, and returns when one frees', async () => {
    const sb = makeSandbox();
    const cap = sb.TerminalAddons.WEBGL_CONTEXT_CAP;
    const others = Array.from({ length: cap }, () => loadHeld(sb));
    const { term, holder, addon } = loadHeld(sb);
    addon.lose();
    await settle(sb, 6);
    assert.equal(sb.addons.length, cap + 1, 'no new WebglAddon at the cap');
    assert.equal(holder._webglAddon, null);

    others[3].addon.dispose();
    await settle(sb, 6);
    assert.equal(sb.addons.length, cap + 2, 'the evicted pane re-armed');
    assert.equal(holder._webglAddon, sb.addons[cap + 1]);
    assert.equal(term.refreshes.length, 1);
});

test('a pane evicted while the tab was hidden re-arms once, and redraws once, when shown', async () => {
    const sb = makeSandbox();
    const { term, holder, addon } = loadHeld(sb);
    sb.document.visibilityState = 'hidden';
    addon.lose();
    await settle(sb, 3);
    assert.equal(sb.addons.length, 1, 'hidden: not re-armed');
    sb.document.visibilityState = 'visible';
    sb.events.visibilitychange();
    await settle(sb, 6);
    assert.equal(sb.addons.length, 2);
    assert.ok(holder._webglAddon);
    assert.deepEqual(term.refreshes, [[0, 23]]);
    await settle(sb, 3);
    assert.equal(sb.addons.length, 2, 'once');
});

test('a re-armed addon that loses its context again is retried at most twice, never faster than the interval', async () => {
    const sb = makeSandbox();
    const { holder, addon } = loadHeld(sb);
    addon.lose();
    for (let round = 0; round < 5; round += 1) {
        sb.events.visibilitychange();
        await settle(sb, 4);
        const live = sb.addons[sb.addons.length - 1];
        if (holder._webglAddon === live) live.lose();
    }
    assert.equal(sb.addons.length, 1 + sb.TerminalAddons.MAX_REARMS, 'the original plus two re-arms');
    assert.equal(holder._webglAddon, null);

    const sb2 = makeSandbox();
    const h2 = loadHeld(sb2);
    h2.addon.lose();
    sb2.clock.now += sb2.TerminalAddons.REARM_MIN_INTERVAL_MS + 1;
    sb2.events.visibilitychange();
    await sleep(sb2.TerminalAddons.UNPAINTED_POLL_MS * 4);
    assert.equal(sb2.addons.length, 2);
    sb2.addons[1].lose();
    sb2.events.visibilitychange();
    await sleep(sb2.TerminalAddons.UNPAINTED_POLL_MS * 4);
    assert.equal(sb2.addons.length, 2, 'inside the interval: no third addon');
});

test('a window focus redraws every live painted WebGL pane once, and no evicted one', async () => {
    const sb = makeSandbox();
    const a = loadHeld(sb);
    const b = loadHeld(sb);
    const covered = loadHeld(sb);
    const evicted = loadHeld(sb);
    covered.term.element.painted = false;
    evicted.addon.lose();
    sb.events.focus();
    await sleep(sb.TerminalAddons.UNPAINTED_POLL_MS * 3);
    assert.deepEqual(a.term.refreshes, [[0, 23]]);
    assert.deepEqual(b.term.refreshes, [[0, 23]]);
    assert.equal(covered.term.refreshes.length, 0, 'not painted: not touched');
    assert.equal(evicted.term.refreshes.length, 0, 'on the DOM renderer: not touched');
});

test('a disposed terminal leaves the live count and is never re-armed', async () => {
    const sb = makeSandbox();
    const cap = sb.TerminalAddons.WEBGL_CONTEXT_CAP;
    const gone = loadHeld(sb);
    gone.addon.dispose();
    const evicted = loadHeld(sb);
    evicted.addon.lose();
    evicted.term.element.isConnected = false;
    sb.events.visibilitychange();
    await settle(sb, 5);
    assert.equal(sb.addons.length, 2, 'neither was re-armed');
    const room = Array.from({ length: cap - 1 }, () => loadHeld(sb));
    assert.equal(room.length, cap - 1);
    const late = loadHeld(sb);
    late.addon.lose();
    sb.events.visibilitychange();
    await settle(sb, 5);
    assert.equal(sb.addons.length, 2 + cap - 1 + 1 + 1, 'one live pane fewer than the cap: the late pane re-armed');
});

test('a minimized desktop window withdraws its size vote, and restoring rejoins (visibilityState never leaves visible)', () => {
    const handlers = {};
    const fired = [];
    const doc = { visibilityState: 'visible', dispatchEvent(e) { fired.push(e.type); (handlers.visibilitychange || []).forEach((fn) => fn()); } };
    const win = {
        console: { log() {}, warn() {}, error() {} }, document: doc, carnivoreDesktop: {}, location: { origin: 'http://127.0.0.1:8000' },
        Event: class { constructor(type) { this.type = type; } },
        addEventListener(type, fn) { (handlers[type] ||= []).push(fn); },
        setTimeout, clearTimeout,
    };
    win.window = win;
    vm.createContext(win);
    for (const file of ['client/js/desktop-window-hidden.js', 'client/js/terminal-size-vote.js']) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, file), 'utf8'), win, { filename: file });
    }
    const vote = win.TerminalSizeVote;
    const sent = [];
    const ctl = { term: {}, sendResize: (why, hidden) => sent.push([why, hidden === true]), _chrome: () => null };
    handlers.visibilitychange = [() => vote.onVisibilityChange(ctl, doc)];
    const self = vm.runInContext('window', win);
    const post = (data, source = self, origin = 'http://127.0.0.1:8000') => handlers.message.forEach((fn) => fn({ source, origin, data }));

    assert.equal(vote.isHidden(doc), false);
    post({ type: 'carnivore.window-hidden', hidden: true });
    assert.equal(doc.visibilityState, 'visible', 'the document still says visible: that is the defect');
    assert.equal(vote.isHidden(doc), true, 'the shell said minimized');
    assert.deepEqual(sent, [['visibility.hidden', true]], 'the vote was withdrawn with the hidden flag, never a faked size');
    post({ type: 'carnivore.window-hidden', hidden: true });
    assert.equal(sent.length, 1, 'repeating the same state sends nothing');
    post({ type: 'carnivore.window-hidden', hidden: false });
    assert.equal(vote.isHidden(doc), false);
    assert.equal(fired.length, 2, 'one visibilitychange per change');
    post({ type: 'carnivore.window-hidden', hidden: true }, {});
    post({ type: 'carnivore.window-hidden', hidden: true }, self, 'http://evil.example');
    post({ type: 'carnivore.window-hidden', hidden: 'yes' });
    assert.equal(vote.isHidden(doc), false);
});

test('a browser tab (no bridge) ignores the message; the preload and the host wire the channel', () => {
    const win = { console: { log() {} }, document: {}, addEventListener() { throw new Error('a browser tab must not listen'); } };
    win.window = win;
    vm.createContext(win);
    vm.runInContext(fs.readFileSync(path.join(ROOT, 'client/js/desktop-window-hidden.js'), 'utf8'), win);
    const preload = fs.readFileSync(path.join(ROOT, 'macOS/app-window-preload.js'), 'utf8');
    const host = fs.readFileSync(path.join(ROOT, 'macOS/window-host.js'), 'utf8');
    assert.match(preload, /ipcRenderer\.on\('carnivore:window-hidden'/);
    assert.match(host, /'carnivore:window-hidden', win\.isMinimized\(\) \|\| !win\.isVisible\(\)/);
    for (const name of ['minimize', 'restore', 'hide', 'show']) assert.ok(host.includes(`'${name}'`), name);
    assert.match(fs.readFileSync(path.join(ROOT, 'client/index.html'), 'utf8'), /desktop-window-hidden\.js/);
});
