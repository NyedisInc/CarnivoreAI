// and the real
// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

let passes = 0;
let failures = 0;

async function test(name, fn) {
    try {
        await fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(String(err && err.message || err).slice(0, 300), (err && err.stack || "").split("\n").slice(1, 4).map((l) => l.slice(0, 120)).join(" | "));
    }
}

function makeContext(opts = {}) {
    const clicked = [];
    const timers = { count: 0 };
    const doc = {
        body: { appendChild() {} },
        createElement() {
            const a = { style: {}, remove() {}, click() { clicked.push(a.href); } };
            return a;
        },
        getElementById() { return null; },
    };
    const ctx = {
        console: { log() {}, warn: console.warn, error: console.error },
        matchMedia: (q) => ({ matches: q === '(hover: none)' && !!opts.touchOnly }),
        setTimeout: (...a) => { timers.count++; return setTimeout(...a); },
        clearTimeout,
        setInterval: (...a) => { timers.count++; return setInterval(...a); },
        clearInterval,
        queueMicrotask,
        URL,
    };
    ctx.self = ctx;
    ctx.window = ctx;
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    vm.runInContext(read('client/vendor/xterm/xterm.js'), ctx);
    vm.runInContext(read('client/vendor/xterm/xterm-addon-web-links.js'), ctx);
    ctx.navigator = { platform: opts.platform || 'MacIntel', userAgent: 'node' };
    ctx.document = doc;
    vm.runInContext(read('client/js/terminal-client-factory.js'), ctx);
    vm.runInContext(read('client/js/terminal-links.js'), ctx);
    return { ctx, clicked, timers };
}

function linkedTerminal(ctx) {
    const term = new ctx.Terminal({ allowProposedApi: true, scrollback: 5000, cols: 80, rows: 24 });
    const calls = { n: 0 };
    let provider = null;
    const real = term.registerLinkProvider.bind(term);
    term.registerLinkProvider = (p) => {
        const orig = p.provideLinks.bind(p);
        p.provideLinks = (y, cb) => { calls.n++; return orig(y, cb); };
        provider = p;
        return real(p);
    };
    assert.ok(ctx.TerminalLinks.attach(term), 'attach returns the add-on');
    return { term, calls, provider: () => provider };
}

/** Write and wait for xterm to finish parsing. */
const write = (term, data) => new Promise((r) => term.write(data, r));

const linksAt = (p, y) => new Promise((r) => p.provideLinks(y, (l) => r(l || [])));

await test('a 200,000-line flood of URLs makes zero link-finder calls', async () => {
    const { ctx } = makeContext();
    const { term, calls, provider } = linkedTerminal(ctx);
    const line = 'see https://example.com/path?q=1 for more\r\n';
    for (let i = 0; i < 20; i++) await write(term, line.repeat(10000));
    assert.equal(calls.n, 0, 'no provider call during output');
    const links = await linksAt(provider(), term.buffer.active.length - 1);
    assert.equal(calls.n, 1);
    assert.equal(links.length, 1);
    assert.equal(links[0].text, 'https://example.com/path?q=1');
});

await test('attaching registers no timer and no write, data or render listener', () => {
    const { ctx, timers } = makeContext();
    const term = new ctx.Terminal({ allowProposedApi: true });
    const before = timers.count;
    const hooked = [];
    for (const ev of ['onWriteParsed', 'onData', 'onRender', 'onLineFeed', 'onCursorMove', 'onScroll']) {
        const desc = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(term), ev);
        if (!desc || !desc.get) continue;
        Object.defineProperty(term, ev, { get() { hooked.push(ev); return desc.get.call(term); } });
    }
    assert.ok(ctx.TerminalLinks.attach(term));
    assert.equal(timers.count, before, 'no timer');
    assert.deepEqual(hooked, [], 'no output listener');
});

await test('a URL stops at a box-drawing border', async () => {
    const { ctx } = makeContext();
    const { term, provider } = linkedTerminal(ctx);
    await write(term, '│ https://example.com/a│ ──\r\n');
    const links = await linksAt(provider(), 1);
    assert.equal(links.length, 1);
    assert.equal(links[0].text, 'https://example.com/a');
});

await test('Mac: Cmd-click opens http(s); a plain click does not', () => {
    const { ctx, clicked } = makeContext({ platform: 'MacIntel' });
    ctx.TerminalLinks.activate({ metaKey: false, ctrlKey: true }, 'https://a.example/');
    assert.deepEqual(clicked, []);
    ctx.TerminalLinks.activate({ metaKey: true }, 'https://a.example/');
    ctx.TerminalLinks.activate({ metaKey: true }, 'http://b.example/x');
    assert.deepEqual(clicked, ['https://a.example/', 'http://b.example/x']);
});

await test('javascript:, file: and data: never open, even with Cmd held', () => {
    const { ctx, clicked } = makeContext();
    for (const uri of ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,hi', 'not a url']) {
        ctx.TerminalLinks.activate({ metaKey: true }, uri);
    }
    assert.deepEqual(clicked, []);
});

await test('elsewhere Ctrl is the modifier; a touch-only device opens on a plain tap', () => {
    const linux = makeContext({ platform: 'Linux x86_64' });
    linux.ctx.TerminalLinks.activate({ metaKey: true }, 'https://a.example/');
    linux.ctx.TerminalLinks.activate({ ctrlKey: true }, 'https://b.example/');
    assert.deepEqual(linux.clicked, ['https://b.example/']);
    const phone = makeContext({ platform: 'iPhone', touchOnly: true });
    phone.ctx.TerminalLinks.activate({}, 'https://c.example/');
    assert.deepEqual(phone.clicked, ['https://c.example/']);
});

console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL PASS (${passes})`);
process.exit(failures ? 1 : 0);
