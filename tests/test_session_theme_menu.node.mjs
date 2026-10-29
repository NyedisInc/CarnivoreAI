
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
function clientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

const popoverSrc = clientJs('anchor-popover.js');
const src = clientJs('session-theme-menu.js');

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

function fakeEl(id) {
    return {
        id,
        attrs: {},
        handlers: {},
        classes: new Set(),
        children: [],
        style: {},
        setAttribute(k, v) { this.attrs[k] = v; },
        getAttribute(k) { return this.attrs[k]; },
        addEventListener(type, fn) { this.handlers[type] = fn; },
        appendChild(c) { this.children.push(c); },
        removeChild() {},
        remove() {},
        contains() { return false; },
        classList: {
            add() {}, remove() {},
            toggle(name, on) { if (on) this.__on = name; },
        },
        getBoundingClientRect() {
            return { top: 0, bottom: 10, left: 0, right: 10 };
        },
        offsetWidth: 10,
        offsetHeight: 10,
    };
}

function load(opts) {
    const created = [];
    const calls = { applyGlobal: [], pins: [] };

    const sandbox = {
        window: {
            Themes: {
                getActiveSession: () => opts.session,
                getActiveGlobal: () => ({ id: 'claude', name: 'Claude' }),
                getSessionManifest: context => ({ id: context.pinnedTheme }),
                pinThemeForSession: async (name, id) => { calls.pins.push([name, id]); return opts.save !== false; },
                listAll: () => [
                    { id: 'claude', name: 'Claude' },
                    { id: 'matrix', name: 'Matrix' },
                ],
                applyGlobal(id) { calls.applyGlobal.push(id); return true; },
            },
            getSelection: () => ({ removeAllRanges() {}, addRange() {} }),
            innerWidth: 400,
            innerHeight: 800,
        },
        localStorage: {
            getItem: () => null,
            setItem: () => {},
        },
        document: {
            body: { appendChild() {} },
            createElement: () => {
                const el = fakeEl('created');
                created.push(el);
                return el;
            },
            addEventListener() {},
            removeEventListener() {},
            getElementById: () => null,
        },
        console: { log() {}, warn() {} },
        setTimeout: (fn) => fn(),
        Date,
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(popoverSrc, sandbox);
    vm.runInContext(src, sandbox);
    return {
        api: sandbox.window.SessionThemeMenu,
        calls,
        created,
    };
}

test('the picker lists every registered theme and marks the active one', () => {
    const { api, created } = load({ session: 'alpha' });
    api.open(fakeEl('sessionThemeBtn'));
    const rows = created.filter((el) => el.handlers.click);
    assert.equal(rows.length, 2, 'one row per theme');
    assert.equal(rows[0].textContent, 'claude');
    assert.equal(rows[1].textContent, 'matrix');
    assert.equal(rows[0].getAttribute('aria-checked'), 'true');
    assert.equal(rows[1].getAttribute('aria-checked'), 'false');
});

test('picking a theme routes through applyGlobal (server-side per-session pin)', () => {
    const { api, calls, created } = load({ session: 'alpha' });
    api.open(fakeEl('sessionThemeBtn'));
    assert.equal(calls.applyGlobal.length, 0, 'opening alone must apply nothing');

    const rows = created.filter((el) => el.handlers.click);
    rows[1].handlers.click();

    assert.equal(calls.applyGlobal.join(','), 'matrix');
});

test('the picker names the session it is scoped to', () => {
    const { api, created } = load({ session: 'my-project-Main' });
    api.open(fakeEl('sessionThemeBtn'));
    const head = created.find(
        (el) => typeof el.textContent === 'string' && el.textContent.indexOf('theme for ') === 0
    );
    assert.ok(head, 'header present');
    assert.equal(head.textContent, 'theme for my-project-Main');
});

test('the picker is placed by the SHARED anchor rule, not a local copy', () => {
    const { api, created } = load({ session: 'alpha' });
    const anchor = fakeEl('sessionThemeBtn');
    api.open(anchor);
    const picker = created[0];
    assert.equal(typeof picker.style.left, 'string',
        'the picker must have been positioned');
    assert.equal(typeof picker.style.top, 'string');
    assert.ok(!src.includes('visualViewport'),
        'placement must live in anchor-popover.js, not be copied back in');
    assert.ok(popoverSrc.includes('visualViewport'),
        'the shared rule must still clamp to the visual viewport');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('THE REMOVED FEATURE: no sound control is reachable here any more', () => {
    assert.ok(src.length > 1000,
        'the module source came back empty, so the assertions below prove nothing');
    assert.ok(
        !/isAudioOn|setAudioOn|toggleAudio|AUDIO_KEY_PREFIX|syncForSession|setSessionAudio/.test(src),
        'session-theme-menu.js must not carry a per-session sound opt-in any more'
    );
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    assert.ok(!/audioToggleBtn/.test(html),
        'the header app sound toggle must stay deleted');
    assert.ok(!/ThemeAudio|GlobalAudioToggle|SettingsAudio/.test(html),
        'index.html must load no sound module');
});

for (const save of [true, false]) {
    const { api, calls, created } = load({ session: 'primary', save });
    const selected = [];
    api.open(fakeEl('secondary-theme'), {
        sessionName: 'secondary', pinnedTheme: 'matrix', agentType: null,
        onSelected: id => selected.push(id),
    });
    const rows = created.filter(el => el.handlers.click);
    assert.equal(rows[1].getAttribute('aria-checked'), 'true');
    await rows[0].handlers.click();
    assert.deepEqual(calls.pins, [['secondary', 'claude']]);
    assert.deepEqual(calls.applyGlobal, []);
    assert.deepEqual(selected, save ? ['claude'] : []);
    passes++;
}

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.error('FAILURES');
    process.exit(1);
}
console.log('ALL PASS');
