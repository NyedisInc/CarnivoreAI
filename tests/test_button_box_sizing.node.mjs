
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let failures = 0;
let passes = 0;

/**
 * Run one named assertion block, recording pass/fail rather than throwing.
 * @param {string} name  Test description.
 * @param {() => void} fn  Body; throwing marks the test failed.
 * @returns {void}
 */
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

/**
 * Read one file from the client directory.
 * @param {...string} parts  Path segments below `client/`.
 * @returns {string} File contents.
 */
function clientFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', ...parts), 'utf8');
}

function rules(source) {
    const clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(clean)) !== null) {
        const selector = m[1].trim().replace(/\s+/g, ' ');
        if (!selector || selector.startsWith('@')) continue;
        out.push({ selector, body: m[2] });
    }
    return out;
}

function bySelector(ruleList, wanted) {
    return ruleList.filter((r) => r.selector.split(',').some((s) => s.trim() === wanted));
}

function decl(body, prop) {
    const m = body.match(new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`, 'i'));
    return m ? m[1].trim() : null;
}

const stylesCss = clientFile('css', 'styles.css');
const toastCss = clientFile('css', 'toast.css');
const sidebarCss = clientFile('css', 'session-sidebar.css');
const indexHtml = clientFile('index.html');

const styleRules = rules(stylesCss);
const toastRules = rules(toastCss);
const sidebarRules = rules(sidebarCss);

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('no bare `button` element rule exists any more', () => {
    const bare = bySelector(styleRules, 'button');
    assert.deepEqual(bare, [], 'expected zero bare `button` element rules in styles.css');
});

test('.btn-icon pins the round header icon controls to a control-size square', () => {
    const reset = bySelector(styleRules, '.btn-icon').filter((r) => decl(r.body, 'width'));
    assert.equal(reset.length, 1, 'expected exactly one `.btn-icon` rule to set the box');
    assert.equal(decl(reset[0].body, 'width'), 'var(--control-size)');
    assert.equal(decl(reset[0].body, 'height'), 'var(--control-size)');
});

test('.btn-icon is applied to exactly the four static buttons that need it', () => {
    assert.match(indexHtml, /id="configEditorBtn"[^>]*class="btn-icon hidden"/,
        '#configEditorBtn should carry the btn-icon class');
    assert.match(indexHtml, /id="launchpad-help-btn"[^>]*class="btn-icon"/,
        '#launchpad-help-btn should carry the btn-icon class');
    assert.match(indexHtml, /id="terminalSearchBtn"[^>]*class="btn-icon"/,
        '#terminalSearchBtn should carry the btn-icon class');
    assert.match(indexHtml, /id="sessionNotesBtn" class="btn-icon hidden"/,
        '#sessionNotesBtn should carry the btn-icon class');
    const withClass = [...indexHtml.matchAll(/<button[^>]*class="([^"]*)"[^>]*>/g)]
        .filter((m) => m[1].split(/\s+/).includes('btn-icon'));
    assert.equal(withClass.length, 4,
        'btn-icon should be on exactly four static <button>s '
        + '(#configEditorBtn, #sessionNotesBtn, #launchpad-help-btn, '
        + 'and #terminalSearchBtn)');
});

test('box-sizing is border-box, which is why the reset eats padding', () => {
    const star = bySelector(styleRules, '*');
    assert.ok(star.length > 0, 'expected the `*` base rule in styles.css');
    assert.ok(star.some((r) => decl(r.body, 'box-sizing') === 'border-box'),
        'without border-box the reset would not absorb a class\'s own padding');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

const OPT_OUTS = [
    ['styles.css', styleRules, '.cloude-touch-copy', ['width', 'height']],
    ['styles.css', styleRules, '.auth-container .auth-button', ['height']],
    ['toast.css', toastRules, '.toast__dismiss', ['width', 'height']],
];

for (const [sheet, ruleList, selector, axes] of OPT_OUTS) {
    test(`${selector} declares its own box, not the control-size square`, () => {
        const hits = bySelector(ruleList, selector);
        assert.ok(hits.length > 0, `${selector} rule not found in ${sheet}`);
        const body = hits.map((r) => r.body).join(';');
        assert.ok(decl(body, 'padding') || decl(body, 'padding-top'),
            `${selector} is only in this list because it declares padding; `
            + 'if that is gone, retire the entry rather than the assertion');
        for (const axis of axes) {
            assert.equal(decl(body, axis), 'auto',
                `${selector} must declare ${axis}: auto, or the bare button `
                + `reset sets ${axis} to var(--control-size) and swallows its padding`);
        }
    });
}

test('.reset-server-btn and .new-session-btn are gone, not merely restyled', () => {
    for (const sel of ['.reset-server-btn', '.new-session-btn']) {
        assert.deepEqual(bySelector(styleRules, sel), [],
            `${sel} styles a control that no template or script renders; `
            + 'if the control comes back, add the rule and the markup together');
    }
});

test('.auth-button ends up the same order of height as .auth-input', () => {
    const btn = bySelector(styleRules, '.auth-container .auth-button').map((r) => r.body).join(';');
    const input = bySelector(styleRules, '.auth-input').map((r) => r.body).join(';');
    assert.ok(/padding:\s*7px/.test(btn), '.auth-button should keep its 7px vertical padding');
    assert.ok(/padding:\s*7px/.test(input), '.auth-input should keep its 7px vertical padding');
});


test('the sidebar collapse control is sized as a header control, not a bare button', () => {
    const header = fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', 'drawer', 'DrawerHeader.svelte'), 'utf8');
    assert.match(header, /<IconButton [^>]*variant="quiet" id="session-sidebar-collapse"/,
        'the collapse key is the base quiet icon button');
    assert.match(header, /:global\(\[data-dh-key\]\)\s*\{[^}]*--oc-ibtn-size:\s*28px/, 'and declares its own 28px box');
    assert.ok(!/\.session-sidebar-collapse\s*\{/.test(sidebarCss),
        'no unlayered rule of the old hand-made button is left to beat the shared one');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('.running-session-name can shrink, so a long name cannot push the row wide', () => {
    const name = bySelector(styleRules, '.running-session-name');
    assert.ok(name.length > 0, '.running-session-name rule not found');
    const body = name[0].body;
    assert.equal(decl(body, 'min-width'), '0',
        'without this the name is a flex item at its content size; measured '
        + 'at 390px an all-underscore session name laid out 501px wide in a '
        + '280px row and pushed the kill control 293px off-screen');
    assert.equal(decl(body, 'overflow'), 'hidden',
        'overflow: hidden is the declaration that actually zeroes the '
        + 'automatic minimum size - min-width alone is not enough here');
    assert.equal(decl(body, 'text-overflow'), 'ellipsis');
    assert.equal(decl(body, 'white-space'), null,
        'deliberately NOT nowrap: ordinary multi-word names should still '
        + 'wrap, this only bounds an unbreakable token');
});

test('.running-session-top is the flex container that makes the above matter', () => {
    const top = bySelector(styleRules, '.running-session-top');
    assert.ok(top.length > 0, '.running-session-top rule not found');
    assert.equal(decl(top[0].body, 'display'), 'flex');
});

test('the two picker names already shrink and need no min-width', () => {
    for (const sel of ['.folder-picker-name', '.provider-item-name']) {
        const body = bySelector(styleRules, sel).map((r) => r.body).join(';');
        assert.ok(body, `${sel} rule not found`);
        assert.equal(decl(body, 'overflow'), 'hidden', `${sel} must keep overflow: hidden`);
        assert.equal(decl(body, 'text-overflow'), 'ellipsis');
        assert.equal(decl(body, 'white-space'), 'nowrap');
    }
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
