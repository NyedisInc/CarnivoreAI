
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import assert from 'node:assert/strict';

import CATALOG from '../client/js/i18n/catalog.en.js';
import {
    terminalKeyBarLabels, TERMINAL_KEY_BAR_KEYS,
} from '../client/js/labels/terminal-key-bar.js';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const BAR_SRC = read('client/js/terminal-key-bar.js');
const DPAD_SRC = read('client/js/dpad.js');
const COMPILED_ICONS = new Set([...read('web/src/opscenter/ui/icons.ts')
    .matchAll(/^\s+"([a-z-]+)":/gm)].map((m) => m[1]));
const LEGACY_GLYPHS = new Set([...read('client/js/icons/glyphs.js')
    .matchAll(/^    ([a-z-]+): \[/gm)].map((m) => m[1]));

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

function fakeNode(tag) {
    const node = {
        tagName: tag,
        attrs: {},
        dataset: {},
        children: [],
        listeners: {},
        innerHTML: '',
        _text: '',
        get textContent() { return this._text; },
        set textContent(v) { this._text = v; this.children = []; },
        setAttribute(k, v) { this.attrs[k] = v; },
        getAttribute(k) { return this.attrs[k]; },
        appendChild(child) { this.children.push(child); child.parent = node; return child; },
        addEventListener(type, fn) {
            (this.listeners[type] = this.listeners[type] || []).push(fn);
        },
        contains(other) {
            for (let n = other; n; n = n.parent) if (n === node) return true;
            return false;
        },
        closest(sel) {
            const key = sel.replace(/^\[|\]$/g, '');
            for (let n = this; n; n = n.parent) {
                if (key === 'data-key-bar-action' && n.dataset.keyBarAction) return n;
            }
            return null;
        },
    };
    return node;
}

function realm(opts = {}) {
    const sent = [];
    const opened = [];
    const pasted = [];
    const screen = fakeNode('div');
    const terminalController = {
        name: 'the terminal wrapper',
        sendKeyToTerminal(code) { sent.push(code); },
    };

    const sandbox = {
        console: { log() {}, warn() {}, debug() {}, error: opts.onError || (() => {}) },
        document: {
            readyState: opts.readyState || 'complete',
            getElementById: (id) => (id === 'terminal-screen' ? screen : null),
            createElement: (tag) => fakeNode(tag),
            addEventListener() {},
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.addEventListener = () => {};
    sandbox.TerminalController = terminalController;
    sandbox.SlashCommandsModal = { open() { opened.push(true); } };
    sandbox.TerminalToolsMenu = {
        toggle(anchor) { pasted.push(anchor); },
    };
    sandbox.CloudeLabels = { terminalKeyBarLabels };
    sandbox.CloudeWeb = {
        iconSvg: (n) => (COMPILED_ICONS.has(n) ? `<svg><path d="M0 0"/></svg>` : ''),
    };
    sandbox.CloudeGlyphs = {
        glyphSvg: (n) => (LEGACY_GLYPHS.has(n) ? `<svg><path d="M0 0"/></svg>` : ''),
    };
    if (!opts.noI18n) {
        sandbox.CloudeI18n = {
            t: (key) => (Object.prototype.hasOwnProperty.call(CATALOG, key)
                ? CATALOG[key] : key),
        };
    }

    vm.createContext(sandbox);
    vm.runInContext(DPAD_SRC, sandbox, { filename: 'dpad.js' });
    vm.runInContext(BAR_SRC, sandbox, { filename: 'terminal-key-bar.js' });
    return {
        bar: sandbox.TerminalKeyBar,
        DPad: sandbox.DPad,
        sent, opened, pasted, screen,
        terminalController,
    };
}

function allKeys(el) {
    return el.children.flatMap((row) => row.children);
}

function tap(r, action) {
    const el = r.bar.element();
    const btn = allKeys(el).find((c) => c.dataset.keyBarAction === action);
    assert.ok(btn, `no button for "${action}"`);
    (el.listeners.click || []).forEach((fn) => fn({
        target: btn, preventDefault() {},
    }));
    return btn;
}


test('the bar mounts into the terminal screen, in flow, at load', () => {
    const r = realm();
    assert.equal(r.screen.children.length, 1, 'exactly one child was added');
    assert.equal(r.screen.children[0], r.bar.element());
    assert.equal(r.bar.element().id, 'terminal-key-bar');
    assert.ok(!BAR_SRC.includes('document.body.appendChild'),
        'nothing here may hang off <body>');
});

test('row 1 is the original keys with enter where agent was; row 2 holds the nine more', () => {
    const r = realm();
    const rows = r.bar.element().children;
    assert.equal(rows.length, 2, 'two rows');
    assert.deepEqual(
        rows[0].children.map((c) => c.dataset.keyBarAction),
        ['slash', 'esc', 'tab', 'up', 'down', 'left', 'right', 'paste', 'enter']);
    assert.deepEqual(
        rows[1].children.map((c) => c.dataset.keyBarAction),
        ['shifttab', 'undo', 'stash', 'sleep', 'theme', 'notes', 'coffee', 'files', 'search']);
});

test('enter sends a carriage return and undo sends ctrl+shift+- (0x1f)', () => {
    const r = realm();
    tap(r, 'enter');
    tap(r, 'undo');
    assert.deepEqual(r.sent, ['\r', '\x1f']);
});

test('stash sends ctrl+s (0x13)', () => {
    const r = realm();
    tap(r, 'stash');
    assert.deepEqual(r.sent, ['\x13']);
});

test('the legacy ordering test, kept for the original eight', () => {
    const r = realm();
    assert.deepEqual(
        allKeys(r.bar.element()).map((c) => c.dataset.keyBarAction).filter((a, i) => i < 8),
        ['slash', 'esc', 'tab', 'up', 'down', 'left', 'right', 'paste']);
});

test('a key that declares a glyph actually PAINTS one', () => {
    const r = realm();
    const declared = terminalKeyBarLabels((k) => k).keys.filter((k) => k.glyph);
    assert.ok(declared.length >= 5, 'the arrows and the two marks all draw glyphs');
    for (const entry of declared) {
        const btn = allKeys(r.bar.element())
            .find((c) => c.dataset.keyBarAction === entry.action);
        assert.ok(btn, `${entry.action} must be rendered at all`);
        const ink = (btn.innerHTML || '') + (btn.children || [])
            .map((c) => c.innerHTML || '').join('');
        assert.ok(/<(path|rect|circle|line|polyline)\b/.test(ink),
            `"${entry.action}" declares glyph "${entry.glyph}" and painted nothing -`
            + ' the name does not match any drawing');
    }
});

const QUIET_ACTIONS = new Set(['esc', 'tab', 'up', 'down', 'left', 'right', 'enter', 'search']);

test('every key has an accessible name, and it comes from the catalog', () => {
    const r = realm();
    const missing = Object.values(TERMINAL_KEY_BAR_KEYS)
        .filter((k) => !Object.prototype.hasOwnProperty.call(CATALOG, k));
    assert.deepEqual(missing, [], 'every key the labels module reads must exist');
    for (const btn of allKeys(r.bar.element())) {
        const name = btn.attrs['aria-label'];
        assert.ok(name && name.length > 1,
            `"${btn.dataset.keyBarAction}" has no accessible name`);
        assert.ok(!Object.values(TERMINAL_KEY_BAR_KEYS).includes(name),
            `"${name}" is a catalog key rendered raw, not copy`);
        if (QUIET_ACTIONS.has(btn.dataset.keyBarAction)) {
            assert.equal(btn.attrs.title, undefined, `"${name}" is obvious and draws no tip`);
        } else {
            assert.equal(btn.attrs.title, name, 'the tooltip and the name agree');
        }
    }
    const keys = allKeys(r.bar.element());
    assert.ok(keys.some((b) => QUIET_ACTIONS.has(b.dataset.keyBarAction)), 'the bar has quiet keys');
    assert.ok(keys.some((b) => b.attrs.title), 'the bar still has a key with a tip');
});


test('THE PAIRING: each arrow, esc and tab sends its OWN sequence', () => {
    const r = realm();
    const expected = [
        ['esc', 'ESC'],
        ['tab', 'TAB'],
        ['up', 'UP'],
        ['down', 'DOWN'],
        ['left', 'LEFT'],
        ['right', 'RIGHT'],
        ['shifttab', 'SHIFT_TAB'],
    ];
    for (const [action, name] of expected) {
        const before = r.sent.length;
        tap(r, action);
        assert.equal(r.sent.length, before + 1,
            `"${action}" wrote nothing to the terminal`);
        assert.equal(r.sent[before], r.DPad.keys[name],
            `"${action}" must send the ${name} sequence`);
    }
    assert.equal(r.DPad.keys.SHIFT_TAB, '\x1b[Z',
        'shift+tab must be CSI Z, the back-tab sequence');

    assert.equal(new Set(r.sent).size, expected.length,
        'no two keys may send the same bytes');
});

test('THE SLASH KEY OPENS THE MODAL, and types nothing', () => {
    const r = realm();
    tap(r, 'slash');
    assert.equal(r.opened.length, 1, 'the slash command modal was opened');
    assert.deepEqual(r.sent, [], 'and nothing was typed into the session');
});

test('THE PASTE KEY OPENS THE TERMINAL TOOLS MENU, anchored to itself', () => {
    const r = realm();
    const btn = tap(r, 'paste');
    assert.equal(r.pasted.length, 1, 'the tools menu was toggled');
    assert.equal(r.pasted[0], btn, 'anchored to the key that was tapped');
    assert.deepEqual(r.sent, [], 'paste is not a keystroke');
});


test('a key whose module failed to load costs its own key and nothing else', () => {
    const r = realm();
    assert.equal(r.bar.press('nonsense'), false, 'an unknown action is refused');
    assert.deepEqual(r.sent, [], 'and writes nothing');
});

test('POSITIVE CONTROL: press() really does report success', () => {
    const r = realm();
    assert.equal(r.bar.press('esc'), true);
    assert.equal(r.bar.press('slash'), true);
    assert.equal(r.bar.press('paste'), true);
});

test('an unknown action never reaches the terminal as garbage', () => {
    const r = realm();
    r.DPad.sendKey('NO_SUCH_KEY');
    assert.deepEqual(r.sent, []);
});

test('a string layer that is merely late does not log an error while the page parses (#1975)', () => {
    const errors = [];
    realm({ noI18n: true, readyState: 'loading', onError: (m) => errors.push(m) });
    assert.deepEqual(errors, []);
});

test('NEGATIVE CONTROL: a string layer still missing after parsing IS logged, once (#1975)', () => {
    const errors = [];
    const r = realm({ noI18n: true, readyState: 'interactive', onError: (m) => errors.push(m) });
    r.bar.paint();
    assert.equal(errors.length, 1);
    assert.match(errors[0], /no string layer/);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.error('FAILURES');
    process.exit(1);
}
console.log('ALL PASS');
