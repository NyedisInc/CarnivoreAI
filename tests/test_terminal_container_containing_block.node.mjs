
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');

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


function stylesheetsInLoadOrder() {
    const html = fs.readFileSync(path.join(repoRoot, 'client', 'index.html'), 'utf8');
    const hrefs = [];
    const re = /<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"/g;
    let m;
    while ((m = re.exec(html)) !== null) hrefs.push(m[1]);
    assert.ok(hrefs.length > 10, `expected the real stylesheet list, got ${hrefs.length}`);
    return hrefs.map((href) => {
        assert.ok(href.startsWith('/static/'), `unexpected stylesheet href: ${href}`);
        return path.join(repoRoot, 'client', href.slice('/static/'.length));
    }).filter((p) => fs.existsSync(p));
}

function stripComments(css) {
    return css.replace(/\/\*[\s\S]*?\*\//g, ' ');
}

function flatten(css, fileIndex) {
    const rules = [];
    let i = 0;
    let ordinal = 0;

    function parseBlock(conditions, depth, layered = false) {
        while (i < css.length) {
            while (i < css.length && /\s/.test(css[i])) i++;
            if (i >= css.length) return;
            if (css[i] === '}') { i++; return; }

            const braceAt = css.indexOf('{', i);
            if (braceAt === -1) return;
            const semiAt = css.indexOf(';', i);
            if (css.startsWith('@layer', i) && semiAt !== -1 && semiAt < braceAt) {
                i = semiAt + 1;
                continue;
            }
            const prelude = css.slice(i, braceAt).trim();

            if (prelude.startsWith('@')) {
                const name = prelude.split(/[\s(]/, 1)[0];
                if (name === '@media' || name === '@supports') {
                    if (depth >= 2) {
                        throw new Error(`nested at-rule too deep to resolve: ${prelude}`);
                    }
                    i = braceAt + 1;
                    parseBlock(conditions.concat(prelude), depth + 1, layered);
                    continue;
                }
                if (name === '@layer') {
                    i = braceAt + 1;
                    parseBlock(conditions, depth, true);
                    continue;
                }
                i = skipBlock(braceAt);
                continue;
            }

            const close = css.indexOf('}', braceAt);
            if (close === -1) return;
            rules.push({
                selectors: prelude.split(',').map((s) => s.trim()).filter(Boolean),
                decls: css.slice(braceAt + 1, close),
                conditions: conditions.slice(),
                layered,
                order: fileIndex * 100000 + (ordinal++),
            });
            i = close + 1;
        }
    }

    function skipBlock(openAt) {
        let j = openAt;
        let depth = 0;
        for (; j < css.length; j++) {
            if (css[j] === '{') depth++;
            else if (css[j] === '}') { depth--; if (depth === 0) return j + 1; }
        }
        return css.length;
    }

    parseBlock([], 0);
    return rules;
}

function buildModel() {
    const rules = [];
    stylesheetsInLoadOrder().forEach((file, idx) => {
        const css = stripComments(fs.readFileSync(file, 'utf8'));
        for (const rule of flatten(css, idx)) {
            rule.file = path.relative(repoRoot, file);
            rules.push(rule);
        }
    });
    return rules;
}

function conditionHolds(condition, width) {
    if (condition.startsWith('@supports')) return true;
    const body = condition.slice('@media'.length).trim();
    const clauses = body.split(/\s+and\s+/);
    return clauses.every((raw) => {
        const clause = raw.trim().replace(/^\(|\)$/g, '');
        if (clause === 'screen' || clause === 'all') return true;
        const m = /^(min|max)-width\s*:\s*(\d+(?:\.\d+)?)px$/.exec(clause);
        if (!m) throw new Error(`media condition not understood: ${raw}`);
        const n = Number(m[2]);
        return m[1] === 'min' ? width >= n : width <= n;
    });
}

function specificity(selector) {
    const ids = (selector.match(/#[\w-]+/g) || []).length;
    const classes = (selector.match(/\.[\w-]+|\[[^\]]*\]|:[\w-]+\(?/g) || []).length;
    const elements = (selector.match(/(^|[\s>+~])[a-zA-Z][\w-]*/g) || []).length;
    return ids * 10000 + classes * 100 + elements;
}

function resolve(rules, selector, property, width) {
    let best = null;
    for (const rule of rules) {
        if (!rule.selectors.includes(selector)) continue;
        if (!rule.conditions.every((c) => conditionHolds(c, width))) continue;
        const re = new RegExp(`(?:^|;)\\s*${property}\\s*:\\s*([^;]+)`, 'i');
        const m = re.exec(rule.decls);
        if (!m) continue;
        const score = (rule.layered ? 0 : 1000000) + specificity(selector);
        if (!best || score > best.score || (score === best.score && rule.order > best.order)) {
            best = { score, order: rule.order, value: m[1].trim(), from: rule.file };
        }
    }
    return best ? { value: best.value, from: best.from } : { value: null, from: null };
}

const MODEL = buildModel();


test('the pane is the containing block: .terminal-container is never static', () => {
    for (const width of [1357, 780, 390]) {
        const got = resolve(MODEL, '.terminal-container', 'position', width);
        assert.ok(got.value, `at ${width}px nothing declares .terminal-container's position`);
        assert.notEqual(
            got.value, 'static',
            `at ${width}px .terminal-container resolves to ${got.value} (from ${got.from}), `
            + 'so every overlay in the pane escapes to #terminal-screen and spans the '
            + 'docked sidebar',
        );
    }
});

test('the declaration lives in the file that owns .terminal-container', () => {
    const got = resolve(MODEL, '.terminal-container', 'position', 1357);
    assert.equal(
        got.from, 'client/css/styles.css',
        `the winning position comes from ${got.from}; it belongs beside the rest of `
        + '.terminal-container, and a second copy elsewhere is how one gets deleted '
        + 'as a duplicate',
    );
});

test('the docked sidebar really does pad .screen, which is what made it matter', () => {
    const pad = resolve(MODEL, '.screen', 'padding-left', 1357);
    assert.match(pad.value || '', /--dock-offset/, 'nothing pads .screen from the dock offset');
    const got = resolve(MODEL, 'body.session-sidebar-pinned', '--dock-offset', 1357);
    assert.ok(got.value, 'the docked body sets no dock offset');
    assert.notEqual(
        got.value.replace(/\s/g, ''), '0',
        'the docked offset is zero, so this test is no longer describing the real layout',
    );
});

test('the search overlays still mount into .terminal-container', () => {
    const ts = fs.readFileSync(
        path.join(repoRoot, 'web', 'src', 'lib', 'terminal-search', 'mount-search.ts'), 'utf8');
    const id = /SEARCH_CONTAINER_ID\s*=\s*'([^']+)'/.exec(ts);
    assert.ok(id, 'could not find SEARCH_CONTAINER_ID in mount-search.ts');
    assert.equal(
        id[1], 'terminal-container',
        'the search panel mounts somewhere else now; move the containing-block rule with it',
    );

    const html = fs.readFileSync(path.join(repoRoot, 'client', 'index.html'), 'utf8');
    assert.match(
        html, /class="terminal-container"\s+id="terminal-container"/,
        '#terminal-container is no longer the element with class .terminal-container',
    );
});



const PRIMARY_CELL_BOXES = ['.oc-tl', '.cc-pane'];

function compiledRulesFor(cls) {
    const css = fs.readFileSync(path.join(repoRoot, 'client', 'dist', 'app.css'), 'utf8');
    const escaped = cls.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(escaped + '(?![-\\w])[^{}]*\\{([^}]*)\\}', 'g');
    const found = [];
    let m;
    while ((m = re.exec(css)) !== null) found.push(m[1]);
    assert.ok(found.length > 0,
        `no compiled rule for ${cls}; the class was renamed and this test is `
        + 'measuring nothing');
    return found;
}

test('the boxes between the frame and the pane are transparent to layout', () => {
    for (const cls of PRIMARY_CELL_BOXES) {
        for (const decls of compiledRulesFor(cls)) {
            for (const prop of ['padding', 'border', 'overflow']) {
                const re = new RegExp('(^|;)\\s*' + prop + '[-a-z]*\\s*:', 'i');
                assert.ok(!re.test(decls),
                    `${cls} declares ${prop} (${decls.trim()}), which costs the `
                    + 'session rows and columns on top of the frame');
            }
            assert.ok(!/(^|;)\s*position\s*:/i.test(decls),
                `${cls} declares position (${decls.trim()}); a containing block `
                + 'above .terminal-container is one the overlays are not inside');
            assert.ok(!/(^|;)\s*(transform|filter|perspective|contain)\s*:/i.test(decls),
                `${cls} declares a property that makes a containing block `
                + `(${decls.trim()})`);
        }
    }
});

test('NEGATIVE CONTROL: the compiled reader can see a declaration it is given', () => {
    const decls = compiledRulesFor('.oc-tl').join(';');
    assert.match(decls, /gap\s*:/,
        'the compiled reader found a rule but can read no declaration out of it');
    assert.match(decls, /display\s*:\s*flex/);
});

test('NEGATIVE CONTROL: with the fix removed, the resolver reports static', () => {
    const preFix = MODEL.filter((rule) => !(
        rule.selectors.includes('.terminal-container') && /(?:^|;)\s*position\s*:/i.test(rule.decls)
    ));
    assert.notEqual(
        preFix.length, MODEL.length,
        'nothing was removed, so this control is not reproducing anything',
    );
    const got = resolve(preFix, '.terminal-container', 'position', 1357);
    assert.equal(
        got.value, null,
        'the pre-fix model still declares a position, so the control is not the pre-fix state',
    );
    assert.throws(() => {
        assert.ok(got.value && got.value !== 'static');
    }, 'the positive assertion still passed against the pre-fix model');
});

test('NEGATIVE CONTROL: the resolver can report a value it was not given', () => {
    const got = resolve(MODEL, '.there-is-no-such-selector', 'position', 1357);
    assert.equal(got.value, null, 'the resolver answered for a selector nothing declares');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
