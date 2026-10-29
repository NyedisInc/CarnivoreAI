// ---------------------------------------------------------------------

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createEnvironment } from './mini-dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let passes = 0;
let failures = 0;

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

function readClientFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', ...parts), 'utf8');
}

const HEADER_MENU_SRC = readClientFile('js', 'header-menu.js');
const HEADER_MENU_CSS = readClientFile('css', 'header-menu.css');

function readFoldBreakpoint() {
    const m = /FOLD_QUERY\s*=\s*'\(max-width:\s*(\d+)px\)'/.exec(HEADER_MENU_SRC);
    assert.ok(m, 'header-menu.js must declare FOLD_QUERY as a max-width query in px');
    return Number(m[1]);
}

const BREAKPOINT = readFoldBreakpoint();

const FOLDABLE_IDS = [
    'headerSessionThemeBtn', 'headerDetachBtn', 'headerSizeMasterBtn', 'headerComponentsBtn',
    'configEditorBtn', 'sessionNotesBtn',
    'logoutBtn', 'settingsBtn',
    'headerMasterAllBtn',
];

const STATIC_CONTROL_IDS = [
    'configEditorBtn', 'sessionNotesBtn',
    'logoutBtn', 'settingsBtn',
];

test('header-menu.css gates the trigger on .controls--folded alone', () => {
    assert.match(HEADER_MENU_CSS, /\.header-menu-toggle\s*\{[^}]*display:\s*none/,
        'the trigger must default to not-in-the-layout');
    assert.match(HEADER_MENU_CSS,
        /\.controls--folded\s+\.header-menu-toggle\s*\{[^}]*display:\s*inline-flex/,
        'the trigger must be revealed by nothing except .controls--folded');
});

function load(startWidth) {
    const env = createEnvironment({ matches: startWidth <= BREAKPOINT });
    const document = env.document;
    const header = document.createElement('div');
    header.className = 'header';
    const controls = document.createElement('div');
    controls.className = 'controls';
    for (const id of STATIC_CONTROL_IDS) {
        const btn = document.createElement('button');
        btn.setAttribute('type', 'button');
        btn.setAttribute('id', id);
        controls.appendChild(btn);
    }
    header.appendChild(controls);
    document.body.appendChild(header);

    const sandbox = {
        window: env.window,
        document,
        console: { log() {}, warn() {}, error() {} },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const file of ['kebab-icon.js', 'dismiss-guard.js', 'header-menu.js']) {
        vm.runInContext(readClientFile('js', file), sandbox);
    }

    return {
        controls,
        panel: document.getElementById('header-menu-panel'),
        setWidth(width) {
            env.setMediaMatches(width <= BREAKPOINT);
        },
    };
}

function idsIn(node) {
    return node.children
        .filter((c) => c.tagName === 'BUTTON')
        .map((c) => c.getAttribute('id'));
}

function assertExclusive(controls, panel, width) {
    const folded = controls.classList.contains('controls--folded');
    const inlineIds = idsIn(controls);
    const panelIds = idsIn(panel);

    assert.equal(folded, width <= BREAKPOINT,
        `${width}px: .controls--folded must equal (width <= ${BREAKPOINT}), got ${folded}`);

    for (const id of FOLDABLE_IDS) {
        const inline = inlineIds.includes(id);
        const inPanel = panelIds.includes(id);
        assert.notEqual(inline, inPanel,
            `${width}px: ${id} must be reachable exactly one way, `
            + `got inline=${inline} panel=${inPanel}`);
        assert.equal(inline, !folded, `${width}px: ${id} inline state must match the fold flag`);
    }

    const anyFolded = FOLDABLE_IDS.some((id) => panelIds.includes(id));
    assert.equal(folded, anyFolded,
        `${width}px: .controls--folded must be set iff something is actually in the panel `
        + '(the trigger must never render next to a fully-inline row, and must never be '
        + 'absent while something is strandable)');
}

const NARROW_WIDTHS = [320, 375, 480, 600, 767, BREAKPOINT];
const WIDE_WIDTHS = [BREAKPOINT + 1, 800, 1024, 1280, 1440, 1920];

test(`ascending sweep from ${NARROW_WIDTHS[0]}px to ${WIDE_WIDTHS[WIDE_WIDTHS.length - 1]}px: exactly one of inline/overflow at every step`, () => {
    const { controls, panel, setWidth } = load(NARROW_WIDTHS[0]);
    for (const width of NARROW_WIDTHS.concat(WIDE_WIDTHS)) {
        setWidth(width);
        assertExclusive(controls, panel, width);
    }
});

test(`descending sweep from ${WIDE_WIDTHS[WIDE_WIDTHS.length - 1]}px to ${NARROW_WIDTHS[0]}px: exactly one of inline/overflow at every step`, () => {
    const { controls, panel, setWidth } = load(WIDE_WIDTHS[WIDE_WIDTHS.length - 1]);
    for (const width of WIDE_WIDTHS.slice().reverse().concat(NARROW_WIDTHS.slice().reverse())) {
        setWidth(width);
        assertExclusive(controls, panel, width);
    }
});

test('bouncing back and forth across the exact boundary never strands a control', () => {
    const { controls, panel, setWidth } = load(BREAKPOINT);
    const sequence = [BREAKPOINT, BREAKPOINT + 1, BREAKPOINT, BREAKPOINT + 1,
        BREAKPOINT - 1, BREAKPOINT + 1, BREAKPOINT];
    for (const width of sequence) {
        setWidth(width);
        assertExclusive(controls, panel, width);
        for (const id of FOLDABLE_IDS) {
            const total = idsIn(controls).filter((x) => x === id).length
                + idsIn(panel).filter((x) => x === id).length;
            assert.equal(total, 1, `${id} must exist exactly once at ${width}px`);
        }
    }
});

test('at the narrowest and widest ends of the sweep, the trigger and the folded row are never both visible and never both gone', () => {
    const narrow = load(NARROW_WIDTHS[0]);
    assert.equal(narrow.controls.classList.contains('controls--folded'), true,
        'narrow: the trigger must be the only way to the folded controls');
    assert.deepEqual(idsIn(narrow.panel), FOLDABLE_IDS, 'narrow: panel holds every foldable control');

    const wide = load(WIDE_WIDTHS[WIDE_WIDTHS.length - 1]);
    assert.equal(wide.controls.classList.contains('controls--folded'), false,
        'wide: the trigger must not render - everything it would hold is already on screen');
    assert.deepEqual(idsIn(wide.panel), [], 'wide: panel holds nothing');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
