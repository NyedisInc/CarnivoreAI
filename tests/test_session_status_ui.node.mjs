// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { glyphSvg } from '../client/js/icons/glyphs.js';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;
const queue = [];

/** Queue one named assertion block. Inputs: name, fn. Output: void. */
function test(name, fn) {
    queue.push([name, fn]);
}

/** Run every queued test in order. Inputs: none. Output: Promise<void>. */
async function runQueue() {
    for (const [name, fn] of queue) {
        try {
            await fn();
            passes++;
            console.log(`ok - ${name}`);
        } catch (err) {
            failures++;
            console.error(`NOT OK - ${name}`);
            console.error(err && err.stack ? err.stack : err);
        }
    }
}

function loadStatusUI() {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'session-status-ui.js'),
        'utf8',
    );
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = { window: fakeWindow, console, CloudeGlyphs: { glyphSvg } };
    context.globalThis = context;
    vm.createContext(context);
    vm.runInContext(src, context);
    return fakeWindow.SessionStatusUI;
}

function loadStatusUIWithFlags(uiFlags) {
    const src = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'session-status-ui.js'),
        'utf8',
    );
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = { window: fakeWindow, console, CloudeGlyphs: { glyphSvg } };
    context.globalThis = context;
    if (uiFlags !== undefined) context.UIFlags = uiFlags;
    vm.createContext(context);
    vm.runInContext(src, context);
    return fakeWindow.SessionStatusUI;
}

const StatusUI = loadStatusUI();

function rawAttr(html, attr) {
    const start = html.indexOf(`${attr}="`);
    if (start === -1) return null;
    const from = start + attr.length + 2;
    const end = html.indexOf('"', from);
    if (end === -1) return null;
    return html.slice(from, end);
}

function decodeEntities(raw) {
    return raw
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&');
}

const HOSTILE = `cloude_"><img src=x onerror='alert(1)'>evil`;

test('escapeAttr handles all five characters, ampersand first', () => {
    assert.equal(StatusUI.escapeAttr('a"b\'c<d>e&f'), 'a&quot;b&#39;c&lt;d&gt;e&amp;f');
    assert.equal(StatusUI.escapeAttr('&lt;'), '&amp;lt;');
    assert.equal(StatusUI.escapeAttr(null), '');
    assert.equal(StatusUI.escapeAttr(undefined), '');
});

test('a hostile session name cannot break out of data-mark-unread', () => {
    const html = StatusUI.markUnreadHtml(HOSTILE, false);
    assert.equal((html.match(/<span/g) || []).length, 1, 'one span only');
    assert.ok(!html.includes('<img'), 'no injected element');
    const raw = rawAttr(html, 'data-mark-unread');
    assert.ok(raw !== null, 'attribute present');
    assert.ok(raw.includes('onerror'), 'payload text is preserved verbatim');
    assert.equal(
        html.replace(`data-mark-unread="${raw}"`, '').includes('onerror'),
        false,
        'onerror appears only inside the escaped value',
    );
    assert.ok(!raw.includes('"'), 'no literal quote inside the value');
    assert.ok(!raw.includes('<') && !raw.includes('>'), 'no literal angle bracket');
});

test('the escaped name round-trips back to the exact original', () => {
    for (const name of [
        HOSTILE,
        'plain_name',
        'has "quotes" and \'apostrophes\'',
        'a<b>c',
        'ampersand & more',
        'literal &quot; entity text',
        'cloude_proj-2026',
    ]) {
        const raw = rawAttr(StatusUI.markUnreadHtml(name, true), 'data-mark-unread');
        assert.equal(decodeEntities(raw), name, `round trip failed for: ${name}`);
    }
});

test('escaping does not disturb the rest of the toggle markup', () => {
    const off = StatusUI.markUnreadHtml('plain', false);
    const on = StatusUI.markUnreadHtml('plain', true);
    assert.ok(off.includes('aria-pressed="false"') && off.includes('data-unread-current="false"'));
    assert.ok(on.includes('aria-pressed="true"') && on.includes('data-unread-current="true"'));
    assert.ok(on.includes('mark-unread-toggle--active'));
    assert.ok(!off.includes('mark-unread-toggle--active'));
    assert.ok(off.includes('mark unread'));
    assert.ok(on.includes('clear unread'));
    assert.ok(off.includes('<svg') && on.includes('<svg'), 'envelope glyph still rendered');
});

test('a missing name yields an empty attribute rather than "undefined"', () => {
    for (const empty of [undefined, null, '']) {
        assert.equal(rawAttr(StatusUI.markUnreadHtml(empty, false), 'data-mark-unread'), '');
    }
});

test('dotHtml escapes its interpolations too', () => {
    const html = StatusUI.dotHtml('question');
    assert.ok(html.includes('status-dot--question'));
    assert.equal(
        rawAttr(html, 'aria-label'),
        'your turn - the agent needs your permission',
    );
    const unknown = StatusUI.dotHtml('<script>');
    assert.ok(!unknown.includes('<script>'));
    assert.ok(unknown.includes('status-dot--unknown'));
});

test('question and notice are separate keys with separate labels', () => {
    const q = StatusUI.dotHtml('question');
    const n = StatusUI.dotHtml('notice');
    assert.ok(n.includes('status-dot--notice'));
    assert.equal(
        rawAttr(n, 'aria-label'),
        'your turn - the agent wants your attention',
    );
    assert.notEqual(rawAttr(q, 'aria-label'), rawAttr(n, 'aria-label'));
    assert.ok(q.includes('status-dot--question'));
});

test('THE MARK-UNREAD CONTROL IS GATED, AND THE GATE FAILS OPEN', () => {

    assert.ok(
        loadStatusUIWithFlags(undefined).markUnreadHtml('cloude_x', false)
            .includes('data-mark-unread'),
        'no UIFlags must mean shown',
    );

    assert.ok(
        loadStatusUIWithFlags({ showMarkUnreadControl: () => true })
            .markUnreadHtml('cloude_x', false).includes('data-mark-unread'),
        'flag true must mean shown',
    );

    const off = loadStatusUIWithFlags({ showMarkUnreadControl: () => false });
    assert.equal(off.markUnreadHtml('cloude_x', false), '',
                 'flag false must render nothing at all');
    assert.equal(off.markUnreadHtml('cloude_x', true), '',
                 'the already-unread state is gated too');
});

await runQueue();
console.log(`${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
