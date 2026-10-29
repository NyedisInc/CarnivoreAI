
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

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

function clientFile(...parts) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', ...parts), 'utf8');
}


const SHEETS = ['styles.css', 'terminal-tools.css', 'header-menu.css',
    'slash-commands-fab.css', 'terminal-key-bar.css'];

function mediaHolds(prelude, width) {
    const parts = prelude.split(/\s+and\s+/).map((p) => p.trim()).filter(Boolean);
    let sawWidth = false;
    let holds = true;
    for (const part of parts) {
        if (part === 'screen' || part === 'all') continue;
        const min = /^\(\s*min-width:\s*(\d+)px\s*\)$/.exec(part);
        const max = /^\(\s*max-width:\s*(\d+)px\s*\)$/.exec(part);
        if (min) {
            sawWidth = true;
            if (width < Number(min[1])) holds = false;
        } else if (max) {
            sawWidth = true;
            if (width > Number(max[1])) holds = false;
        } else {
            return null;
        }
    }
    return sawWidth ? holds : null;
}

function flatten(source) {
    let clean = source.replace(/\/\*[\s\S]*?\*\//g, '');
    const wrap = /^\s*@layer\s+[\w-]+\s*\{/.exec(clean);
    if (wrap) clean = clean.slice(wrap[0].length).replace(/\}\s*$/, '');
    const out = [];
    let i = 0;
    let media = null;
    let mediaDepth = 0;
    while (i < clean.length) {
        const brace = clean.indexOf('{', i);
        if (brace === -1) break;
        const prelude = clean.slice(i, brace).trim().replace(/\s+/g, ' ');
        if (prelude.startsWith('@media')) {
            media = prelude.slice('@media'.length).trim();
            mediaDepth = 1;
            i = brace + 1;
            continue;
        }
        if (prelude.startsWith('@')) {
            let depth = 1;
            let j = brace + 1;
            while (j < clean.length && depth > 0) {
                if (clean[j] === '{') depth++;
                else if (clean[j] === '}') depth--;
                j++;
            }
            i = j;
            continue;
        }
        const close = clean.indexOf('}', brace);
        if (close === -1) break;
        if (prelude) {
            out.push({ selector: prelude, body: clean.slice(brace + 1, close), media });
        }
        i = close + 1;
        if (mediaDepth > 0) {
            const rest = clean.slice(i);
            const next = rest.search(/\S/);
            if (next !== -1 && rest[next] === '}') {
                media = null;
                mediaDepth = 0;
                i += next + 1;
            }
        }
    }
    return out;
}

function matchOne(selector, el) {
    let rest = selector;
    let scopeOk = true;
    let scopeSpec = 0;
    const scope = /^body:has\(#([\w-]+)\.active\)\s+/.exec(rest);
    if (scope) {
        scopeOk = el.screen === scope[1];
        scopeSpec = 100 + 10 + 1;
        rest = rest.slice(scope[0].length);
    }
    const pseudo = /::[\w-]+$/.exec(rest);
    if (pseudo) rest = rest.slice(0, rest.length - pseudo[0].length);

    if (!/^(?:[#.][\w-]+|\[[\w-]+(?:="[^"]*")?\])+$/.test(rest)) return null;
    const ids = rest.match(/#[\w-]+/g) || [];
    const classes = rest.match(/\.[\w-]+/g) || [];
    const attrs = rest.match(/\[[\w-]+(?:="[^"]*")?\]/g) || [];
    const matches = !pseudo && scopeOk
        && ids.every((s) => s.slice(1) === el.id)
        && classes.every((s) => el.classes.includes(s.slice(1)))
        && attrs.every((s) => el.attrs.includes(/^\[([\w-]+)/.exec(s)[1]));
    return {
        matches,
        specificity: scopeSpec + ids.length * 100
            + (classes.length + attrs.length) * 10 + (pseudo ? 1 : 0),
    };
}

function resolve(el, prop, width) {
    const refused = [];
    let best = null;
    let order = 0;
    for (const sheet of SHEETS) {
        for (const rule of flatten(clientFile('css', sheet))) {
            order++;
            if (rule.media !== null) {
                const holds = mediaHolds(rule.media, width);
                if (holds === null) continue;
                if (holds === false) continue;
            }
            const decl = new RegExp(`(?:^|;)\\s*${prop}\\s*:\\s*([^;]+)`).exec(rule.body);
            if (!decl) continue;
            for (const one of rule.selector.split(',')) {
                const sel = one.trim();
                if (!sel) continue;
                const hit = matchOne(sel, el);
                if (hit === null) {
                    if (sel.includes(el.id) || el.classes.some((c) => sel.includes(c))) {
                        refused.push(`${sheet}: ${sel}`);
                    }
                    continue;
                }
                if (!hit.matches) continue;
                const raw = decl[1].trim();
                const important = /!important$/.test(raw);
                const value = raw.replace(/\s*!important$/, '').trim();
                const rank = [important ? 1 : 0, hit.specificity, order];
                if (best === null || rank > best.rank
                        || (rank[0] > best.rank[0])
                        || (rank[0] === best.rank[0] && rank[1] > best.rank[1])
                        || (rank[0] === best.rank[0] && rank[1] === best.rank[1]
                            && rank[2] > best.rank[2])) {
                    best = { rank, value, from: `${sheet}: ${sel}` };
                }
            }
        }
    }
    return { value: best ? best.value : null, from: best ? best.from : null, refused };
}

function assertParsed(r) {
    assert.deepEqual(r.refused, [],
        'the resolver met a selector it cannot read; extend it rather than '
        + 'letting it report a confident answer it did not actually compute');
}

const FAB = {
    id: 'terminalToolsBtn',
    classes: ['fab-menu-btn', 'terminal-tools-fab'],
    attrs: ['type', 'aria-haspopup', 'aria-expanded', 'aria-controls',
        'aria-label', 'title'],
    screen: 'terminal-screen',
};
const FAB_MENU = {
    id: 'terminalToolsMenu',
    classes: ['fab-menu', 'terminal-tools-menu'],
    attrs: ['role', 'aria-label'],
    screen: 'terminal-screen',
};
const SESSION_THEME_ROW = {
    id: 'headerSessionThemeBtn',
    classes: ['btn-icon'],
    attrs: ['type', 'aria-label', 'title'],
    screen: 'terminal-screen',
};
const DETACH_ROW = {
    id: 'headerDetachBtn',
    classes: ['btn-icon'],
    attrs: ['type', 'aria-label', 'title'],
    screen: 'terminal-screen',
};


const KEY_BAR = {
    id: 'terminal-key-bar',
    classes: [],
    attrs: ['role', 'aria-label'],
    screen: 'terminal-screen',
};


test('the resolver agrees with the browser about a control nobody changed', () => {
    const desktop = resolve(KEY_BAR, 'display', 1280);
    assertParsed(desktop);
    assert.equal(desktop.value, 'none', 'the key bar is touch-only on desktop');
    const phone = resolve(KEY_BAR, 'display', 330);
    assertParsed(phone);
    assert.equal(phone.value, 'flex', 'and it really does paint on a phone');
});

test('CHANGE 1, SUPERSEDED 2026-09-22: the floating tools button does not render at ANY width', () => {
    const html = clientFile('index.html');
    assert.ok(html.includes('id="terminal-screen"'), 'the markup scan must read index.html');
    assert.ok(!html.includes('id="terminalToolsBtn"'), 'no floating tools button in the markup');
    assert.ok(!/class="[^"]*\bfab-menu-btn\b/.test(html), 'no floating button class in the markup');
    const jsDir = path.join(__dirname, '..', 'client', 'js');
    const scripts = fs.readdirSync(jsDir).filter((f) => f.endsWith('.js'));
    assert.ok(scripts.length > 20, 'the script scan must actually read scripts');
    for (const f of scripts) {
        const code = fs.readFileSync(path.join(jsDir, f), 'utf8')
            .replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
        assert.ok(!code.includes('terminalToolsBtn'), `${f} still reaches for the floating button`);
    }
    for (const width of [330, 390, 428, 768]) {
        const r = resolve(FAB, 'display', width);
        assertParsed(r);
        assert.equal(r.value, null,
            `no rule may paint the floating tools button at ${width}px (won by ${r.from})`);
    }
});

test('CHANGE 1: the popup menu is phone only, like the key that opens it', () => {
    assert.equal(resolve(FAB_MENU, 'display', 1280).value, 'none');
    assert.equal(resolve(FAB_MENU, 'display', 330).value, 'flex');
    assert.equal(resolve(FAB_MENU, 'display', 768).value, 'flex');
    assert.equal(resolve(FAB_MENU, 'display', 769).value, 'none');
});


test('KEY BAR: the row is absent at desktop width', () => {
    for (const width of [769, 900, 1280, 1920]) {
        const r = resolve(KEY_BAR, 'display', width);
        assertParsed(r);
        assert.equal(r.value, 'none',
            `the key bar must not render at ${width}px (won by ${r.from})`);
    }
});

test('KEY BAR: the row is present at mobile width', () => {
    for (const width of [330, 390, 428, 768]) {
        const r = resolve(KEY_BAR, 'display', width);
        assertParsed(r);
        assert.equal(r.value, 'flex',
            `the key bar must render at ${width}px (won by ${r.from})`);
    }
});

test('KEY BAR: 768 and 769 are the boundary, matching the tools menu', () => {
    assert.equal(resolve(KEY_BAR, 'display', 768).value, 'flex');
    assert.equal(resolve(KEY_BAR, 'display', 769).value, 'none');
});

test('KEY BAR: the two round buttons it replaced are deleted, not hidden', () => {
    const dead = ['.slash-commands-btn', '.dpad-float-button',
        '.dpad-overlay', '.dpad-key', '.dpad-container'];
    let checked = 0;
    for (const sheet of SHEETS) {
        for (const rule of flatten(clientFile('css', sheet))) {
            checked++;
            for (const one of rule.selector.split(',')) {
                const sel = one.trim();
                for (const gone of dead) {
                    assert.ok(!sel.startsWith(gone),
                        `${gone} must be gone from ${sheet}, found "${sel}"`);
                }
            }
        }
    }
    assert.ok(checked > 100, `only ${checked} rules parsed; the sheets did not load`);
});

test('SLASH MODAL: it is forced off at and above 769px', () => {
    let found = 0;
    for (const sheet of SHEETS) {
        for (const rule of flatten(clientFile('css', sheet))) {
            const hit = rule.selector.split(',').map((s) => s.trim())
                .includes('#slash-commands-modal');
            if (!hit) continue;
            found++;
            assert.ok(rule.media, 'the modal-hiding rule must sit inside a media query');
            assert.equal(mediaHolds(rule.media, 768), false,
                'must not fire below 769px, or the modal could never open on a phone');
            assert.equal(mediaHolds(rule.media, 769), true, 'must fire at 769px');
            assert.match(rule.body, /display\s*:\s*none\s*!important/,
                'must force the modal off with !important - `.modal.active` in '
                + 'styles.css is also `!important`, so anything weaker loses');
        }
    }
    assert.equal(found, 1, 'exactly one #slash-commands-modal rule must hide it');
});


test('CHANGE 2: the old session editor button no longer exists in the markup', () => {
    const html = clientFile('index.html');
    assert.ok(!html.includes('id="sessionEditorBtn"'),
        'the sliders-icon header button must be deleted, not merely hidden');
    for (const id of [SESSION_THEME_ROW.id, DETACH_ROW.id]) {
        assert.ok(!html.includes(`id="${id}"`),
            `${id} is built by header-menu.js, not declared in index.html`);
    }
});

test('CHANGE 2: the two kebab rows render at every width, and only on the terminal screen', () => {
    for (const row of [SESSION_THEME_ROW, DETACH_ROW]) {
        for (const width of [330, 390, 768, 1280]) {
            const r = resolve(row, 'display', width);
            assertParsed(r);
            assert.equal(r.value, 'flex',
                `${row.id} must render at ${width}px on the terminal screen`);
        }
        for (const screen of ['launchpad-screen', 'auth-screen', 'archive-screen']) {
            const r = resolve({ ...row, screen }, 'display', 1280);
            assertParsed(r);
            assert.equal(r.value, 'none',
                `${row.id} must not paint on #${screen}`);
        }
    }
});

test('CHANGE 2: the two kebab rows reuse the header button box, they do not restate one', () => {
    const src = clientFile('js', 'header-menu.js');
    for (const id of [SESSION_THEME_ROW.id, DETACH_ROW.id]) {
        assert.match(src, new RegExp(`id = '${id}'[\\s\\S]{0,200}className = 'btn-icon'`),
            `${id} must carry .btn-icon`);
    }
    assert.ok(!/fab-menu-btn|session-editor-fab/.test(src),
        'the kebab rows must carry nothing of the old FAB');

    const scoped = flatten(clientFile('css', 'header-menu.css'))
        .filter((r) => r.selector.includes('headerSessionThemeBtn')
            || r.selector.includes('headerDetachBtn'));
    assert.ok(scoped.length > 0, 'the gate must declare something');
    const declared = scoped.flatMap((r) =>
        [...r.body.matchAll(/([\w-]+)\s*:\s*[^;]+;/g)].map((m) => m[1]));
    assert.deepEqual([...new Set(declared)], ['display'],
        'the gate owns visibility only; .header-menu-panel button owns the look');

    const styles = clientFile('css', 'styles.css').replace(/\/\*[\s\S]*?\*\//g, '');
    assert.match(styles, /\.btn-icon \{[\s\S]*?width: var\(--control-size\);\s*\n\s*height: var\(--control-size\);/,
        'the box must come from the shared token, not from a local number');
    assert.match(styles, /@media \(max-width: 768px\) \{[\s\S]{0,400}?--control-size: 44px;/);
    assert.match(styles, /@media \(max-width: 480px\) \{[\s\S]{0,400}?--control-size: 40px;/,
        'the phone value is 40px - assert what is true, not what is wanted');
});

test('CHANGE 2: accessibility survives the move into the kebab', () => {
    const src = clientFile('js', 'header-menu.js');
    for (const id of [SESSION_THEME_ROW.id, DETACH_ROW.id]) {
        assert.match(src, new RegExp(`id = '${id}'[\\s\\S]{0,400}setAttribute\\('aria-label'`),
            `${id} must set an accessible name`);
        const labelled = id === DETACH_ROW.id
            ? new RegExp(`${id}: 'header\\.menu\\.`)
            : new RegExp(`id = '${id}'[\\s\\S]{0,400}setAttribute\\('title'`);
        assert.match(src, labelled, `${id} must set a visible row label`);
    }
    assert.match(src, /e\.key === 'Escape'/);
});

test('CHANGE 2: the header still fits two inline controls at 330px', () => {
    const styles = clientFile('css', 'styles.css').replace(/\/\*[\s\S]*?\*\//g, '');
    assert.match(styles, /\.controls \{[\s\S]*?flex-shrink: 0;/,
        'the controls must stay the last thing to give up space');
    const control = 40, padX = 12, gap = 8;
    const controlsW = control * 3 + gap * 2;
    const toggleW = control;
    const left = 330 - padX * 2 - controlsW - toggleW;
    assert.ok(left > 0,
        `the header overflows at 330px: ${controlsW}px of controls plus a `
        + `${toggleW}px toggle leaves ${left}px for the title`);
    assert.ok(left >= 40, `only ${left}px left for the session title at 330px`);
    assert.match(styles, /#appTitle \{[\s\S]*?min-width: 0;/,
        'without min-width: 0 the title cannot shrink and the row overflows');
    assert.match(styles,
        /\.header--home \{\s*\n\s*--home-header-flank-w: calc\(var\(--control-size\) \* 2 \+ 8px\);/);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
