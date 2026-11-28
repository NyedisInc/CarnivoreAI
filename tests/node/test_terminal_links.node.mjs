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
    ctx.navigator = { platform: opts.platform || 'MacIntel', userAgent: 'node' };
    ctx.document = doc;
    vm.runInContext(read('client/vendor/xterm/xterm.js'), ctx);
    vm.runInContext(read('client/vendor/xterm/xterm-addon-web-links.js'), ctx);
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

await test('a hard-wrapped multi-line agy S3 presigned URL stitches completely from any row', async () => {
    const { ctx } = makeContext();
    const { term, provider } = linkedTerminal(ctx);
    term.resize(90, 24);
    const lines = [
        '  Gallery Link (7-day presigned S3 URL)',
        '  https://mockup-galleries-demo.s3.amazonaws.com/mockups/carnivore/new-agent-',
        '  workflow/r1/index.html?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-',
        '  Credential=TESTCRED000000000000%2F20261125%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-',
        '  Date=20261125T183057Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-',
        '  Signature=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef',
        '',
        '  The 5 Blind Directions',
    ];
    await write(term, lines.join('\r\n') + '\r\n');
    const expected = 'https://mockup-galleries-demo.s3.amazonaws.com/mockups/carnivore/new-agent-workflow/r1/index.html?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=TESTCRED000000000000%2F20261125%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20261125T183057Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef';
    for (const row of [2, 4, 6]) {
        const links = await linksAt(provider(), row);
        assert.equal(links.length, 1, `row ${row} should yield 1 stitched link`);
        assert.equal(links[0].text, expected);
        assert.equal(links[0].range.start.y, 2);
        assert.equal(links[0].range.end.y, 6);
        assert.equal(links[0].range.start.x, 3);
    }
    assert.deepEqual(await linksAt(provider(), 7), []);
    assert.deepEqual(await linksAt(provider(), 8), []);
});

await test('a soft-wrapped URL without newlines stitches across xterm isWrapped rows', async () => {
    const { ctx } = makeContext();
    const { term, provider } = linkedTerminal(ctx);
    const longUrl = 'https://example.com/' + 'segment/'.repeat(18) + 'end?ok=1';
    await write(term, longUrl + '\r\n');
    const links1 = await linksAt(provider(), 1);
    const links2 = await linksAt(provider(), 2);
    assert.equal(links1.length, 1);
    assert.equal(links1[0].text, longUrl);
    assert.equal(links2.length, 1);
    assert.equal(links2[0].text, longUrl);
});

await test('a URL followed by normal prose on the next line is NOT merged with the prose', async () => {
    const { ctx } = makeContext();
    const { term, provider } = linkedTerminal(ctx);
    await write(term, '  Visit https://example.com/docs\r\n  Then click the button to continue.\r\n');
    const links1 = await linksAt(provider(), 1);
    assert.equal(links1.length, 1);
    assert.equal(links1[0].text, 'https://example.com/docs');
    assert.equal(links1[0].range.start.y, 1);
    assert.equal(links1[0].range.end.y, 1);
    assert.deepEqual(await linksAt(provider(), 2), []);
});

await test('two separate URLs on consecutive lines remain two distinct links', async () => {
    const { ctx } = makeContext();
    const { term, provider } = linkedTerminal(ctx);
    await write(term, '  https://first.example/one-\r\n  https://second.example/two\r\n');
    const l1 = await linksAt(provider(), 1);
    const l2 = await linksAt(provider(), 2);
    assert.equal(l1.length, 1);
    assert.equal(l1[0].text, 'https://first.example/one-');
    assert.equal(l2.length, 1);
    assert.equal(l2[0].text, 'https://second.example/two');
});

await test('a hard-wrapped URL inside a bordered box strips box borders and trailing prose', async () => {
    const { ctx } = makeContext();
    const { term, provider } = linkedTerminal(ctx);
    await write(term, '│ https://example.com/very/long-\r\n│ path/final?x=1 and more words │\r\n');
    const links = await linksAt(provider(), 1);
    assert.equal(links.length, 1);
    assert.equal(links[0].text, 'https://example.com/very/long-path/final?x=1');
    assert.equal(links[0].range.start.y, 1);
    assert.equal(links[0].range.end.y, 2);
});

await test('a plain click opens http(s); a right or middle click does not', () => {
    const { ctx, clicked } = makeContext({ platform: 'MacIntel' });
    ctx.TerminalLinks.activate({ button: 2 }, 'https://a.example/');
    ctx.TerminalLinks.activate({ button: 1 }, 'https://a.example/');
    assert.deepEqual(clicked, []);
    ctx.TerminalLinks.activate({ button: 0 }, 'https://a.example/');
    ctx.TerminalLinks.activate({ button: 0, metaKey: true }, 'http://b.example/x');
    assert.deepEqual(clicked, ['https://a.example/', 'http://b.example/x']);
});

await test('javascript:, file: and data: never open, even with Cmd held', () => {
    const { ctx, clicked } = makeContext();
    for (const uri of ['javascript:alert(1)', 'file:///etc/passwd', 'data:text/html,hi', 'not a url']) {
        ctx.TerminalLinks.activate({ metaKey: true }, uri);
    }
    assert.deepEqual(clicked, []);
});

await test('any platform opens on a plain click; a touch-only device opens on a plain tap', () => {
    const linux = makeContext({ platform: 'Linux x86_64' });
    linux.ctx.TerminalLinks.activate({ button: 0 }, 'https://b.example/');
    assert.deepEqual(linux.clicked, ['https://b.example/']);
    const phone = makeContext({ platform: 'iPhone', touchOnly: true });
    phone.ctx.TerminalLinks.activate({}, 'https://c.example/');
    assert.deepEqual(phone.clicked, ['https://c.example/']);
});

console.log(failures ? `${failures} FAILED, ${passes} passed` : `ALL PASS (${passes})`);
process.exit(failures ? 1 : 0);
