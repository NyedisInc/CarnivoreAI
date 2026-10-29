
import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

let failures = 0;
let passes = 0;

function test(name, fn) {
    try {
        fn();
        passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

function makeEl(id) {
    return {
        id,
        innerHTML: '',
        className: '',
        parentNode: null,
        children: [],
        insertBefore(node) {
            node.parentNode = this;
            this.children.unshift(node);
            return node;
        },
        removeChild(node) {
            this.children = this.children.filter((c) => c !== node);
            node.parentNode = null;
            return node;
        },
    };
}

function makeContext() {
    const byId = new Map();
    const wrapperEl = makeEl('appTitle');
    const titleEl = makeEl('header-title-text');
    titleEl.parentNode = wrapperEl;
    wrapperEl.children.push(titleEl);
    byId.set('appTitle', wrapperEl);
    byId.set('header-title-text', titleEl);

    const document = {
        getElementById(id) {
            const created = wrapperEl.children.find((c) => c.id === id);
            return created || byId.get(id) || null;
        },
        createElement(tag) {
            return makeEl('');
        },
    };

    const ctx = {
        console: { log() {}, warn() {}, error() {} },
        document,
        setInterval() { return 1; },
        clearInterval() {},
    };
    ctx.window = ctx;
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    return { ctx, titleEl, wrapperEl };
}

function load(ctx, files) {
    for (const file of files) {
        const src = fs.readFileSync(path.join(ROOT, 'client', 'js', file), 'utf8');
        vm.runInContext(src, ctx, { filename: file });
    }
}

const SCRIPTS = [
    'status-led.js',
    'session-status-ui.js',
    'session-header-led.js',
];


test('C: every state reads the way requested', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const UI = ctx.window.SessionStatusUI;

    assert.equal(UI.labelFor('idle'), 'idle - read, nothing running');
    assert.equal(UI.labelFor('finished_unread'), 'done - unread');
    assert.equal(UI.labelFor('notice'), 'your turn - the agent wants your attention');
    assert.equal(UI.labelFor('question'), 'your turn - the agent needs your permission');
    assert.equal(UI.labelFor('working'), 'working');
    assert.equal(UI.labelFor('unknown'), 'not measured');
    assert.equal(UI.labelFor('dead'), 'dead - process exited');
});

test('C: the old shell wording is gone from every state', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const UI = ctx.window.SessionStatusUI;
    for (const key of ['idle', 'unknown', 'working', 'notice', 'question']) {
        assert.ok(
            !UI.labelFor(key).includes('shell'),
            `${key} still mentions a shell`,
        );
    }
});

test('C: the label reaches the rendered title attribute', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const html = ctx.window.SessionStatusUI.dotHtml('idle', { unread: false });
    assert.ok(
        html.includes('title="idle - read, nothing running"'),
        `title not rendered: ${html}`,
    );
});


test('E: a source is appended to the tooltip', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const UI = ctx.window.SessionStatusUI;
    assert.equal(
        UI.labelWithSource('working', 'hook'), 'working (via hooks)',
    );
    assert.equal(
        UI.labelWithSource('idle', 'transcript'),
        'idle - read, nothing running (via transcript)',
    );
});

test('E: an absent or unrecognised source appends nothing', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const UI = ctx.window.SessionStatusUI;
    assert.equal(UI.labelWithSource('working', 'none'), 'working');
    assert.equal(UI.labelWithSource('working', undefined), 'working');
    assert.equal(UI.labelWithSource('working', 'made up'), 'working');
});

test('E: the source changes the tooltip and NOTHING else', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const UI = ctx.window.SessionStatusUI;
    const plain = UI.dotHtml('idle', { unread: false });
    const sourced = UI.dotHtml('idle', { unread: false, status_source: 'hook' });
    const strip = (s) => s
        .replace(/title="[^"]*"/g, '')
        .replace(/aria-label="[^"]*"/g, '');
    assert.equal(strip(plain), strip(sourced));
    assert.ok(sourced.includes('via hooks'));
});


test('D: a matching list row paints a light beside the title', () => {
    const { ctx, titleEl, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update([{ name: 'cloude_a', status: 'working', unread: false }], 'cloude_a');

    const led = wrapperEl.children.find((c) => c.id === HL.LED_ID);
    assert.ok(led, 'no header light was inserted');
    assert.ok(led.innerHTML.includes('title="working"'), led.innerHTML);
    assert.ok(
        wrapperEl.children.indexOf(led) < wrapperEl.children.indexOf(titleEl),
        'the light is not before the title',
    );
});

test('D: it updates in place when the status changes', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update([{ name: 'cloude_a', status: 'working' }], 'cloude_a');
    HL.update([{ name: 'cloude_a', status: 'idle' }], 'cloude_a');

    const leds = wrapperEl.children.filter((c) => c.id === HL.LED_ID);
    assert.equal(leds.length, 1, 'a second light was inserted');
    assert.ok(leds[0].innerHTML.includes('idle - read, nothing running'));
});

test('D: the bind that clears unread turns the light idle', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update(
        [{ name: 'cloude_a', status: 'finished_unread', unread: true }],
        'cloude_a',
    );
    let led = wrapperEl.children.find((c) => c.id === HL.LED_ID);
    assert.ok(led.innerHTML.includes('done - unread'), led.innerHTML);

    HL.update([{ name: 'cloude_a', status: 'idle', unread: false }], 'cloude_a');
    led = wrapperEl.children.find((c) => c.id === HL.LED_ID);
    assert.ok(led.innerHTML.includes('idle - read, nothing running'));
});

test('D: it carries the status source into the header tooltip', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update(
        [{ name: 'cloude_a', status: 'idle', status_source: 'transcript' }],
        'cloude_a',
    );

    const led = wrapperEl.children.find((c) => c.id === HL.LED_ID);
    assert.ok(led.innerHTML.includes('via transcript'), led.innerHTML);
});

test('D: no attached session removes the light rather than freezing it', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update([{ name: 'cloude_a', status: 'working' }], 'cloude_a');
    HL.update([{ name: 'cloude_a', status: 'working' }], null);

    assert.equal(
        wrapperEl.children.filter((c) => c.id === HL.LED_ID).length, 0,
        'a light was left under a header naming something else',
    );
});

test('D: a session with no row in the list paints nothing', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update([{ name: 'cloude_other', status: 'working' }], 'cloude_a');

    assert.equal(HL.rowFor([{ name: 'cloude_other' }], 'cloude_a'), null);
    assert.equal(
        wrapperEl.children.filter((c) => c.id === HL.LED_ID).length, 0,
    );
});

test('D: a SessionInfo is read off the WRAPPER, not off .session', () => {
    const { ctx } = makeContext();
    load(ctx, SCRIPTS);
    const row = ctx.window.SessionHeaderLed.rowFromInfo({
        tmux_session: 'cloude_a',
        activity_status: 'notice',
        unread: true,
        status_source: 'hook',
        session: { id: 'ses_1', unread: false },
    });
    assert.equal(row.name, 'cloude_a');
    assert.equal(row.status, 'notice');
    assert.equal(row.unread, true);
    assert.equal(row.status_source, 'hook');
});

test('D: an older payload with no status_source still renders', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;

    HL.update([{ name: 'cloude_a', status: 'idle' }], 'cloude_a');

    const led = wrapperEl.children.find((c) => c.id === HL.LED_ID);
    assert.ok(led && led.innerHTML.includes('idle - read, nothing running'));
    assert.ok(!led.innerHTML.includes('(via'));
});

test('older sidebar or fallback responses cannot restore a working header', () => {
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    const HL = ctx.window.SessionHeaderLed;
    const older = HL.beginRequest();
    const newer = HL.beginRequest();
    HL.update([{ name: 'a', status: 'question' }], 'a', newer);
    HL.update([{ name: 'a', status: 'working' }], 'a', older);
    const led = wrapperEl.children.find(c => c.id === HL.LED_ID);
    assert.ok(led.innerHTML.includes('permission'));
    HL.clear();
    HL.update([{ name: 'a', status: 'working' }], 'a', newer);
    assert.equal(wrapperEl.children.some(c => c.id === HL.LED_ID), false);
});

{
    const { ctx, wrapperEl } = makeContext();
    load(ctx, SCRIPTS);
    installCloudeWeb(ctx);
    const sidebar = ctx.window.SessionSidebar;
    const header = ctx.window.SessionHeaderLed;
    let resolveOld;
    const oldListing = new Promise(resolve => { resolveOld = resolve; });
    ctx.window.API = {
        listAttachableSessions: async () => [],
        listSessions: () => oldListing,
    };
    sidebar.setActiveSession('A', 'a');
    const pending = sidebar._fetchAndRender();
    sidebar.setActiveSession('B', 'b');
    header.update([{ name: 'b', status: 'question' }], 'b');
    resolveOld([{ tmux_session: 'a', activity_status: 'working', session: { id: 'A' } }]);
    await pending;
    test('navigation while a sidebar fetch is pending preserves the new header', () => {
        assert.equal(sidebar.isOpen, false);
        const led = wrapperEl.children.find(c => c.id === header.LED_ID);
        assert.ok(led.innerHTML.includes('permission'), led.innerHTML);
        assert.equal(sidebar._rows.length, 0, 'old rows must also remain unpublished');
    });
}

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);
