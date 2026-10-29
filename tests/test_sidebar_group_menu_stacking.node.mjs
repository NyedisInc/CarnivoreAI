
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

const groupsCss = clientFile('css', 'session-sidebar-groups.css');
const sidebarCss = clientFile('css', 'session-sidebar.css');
const rowMenuCss = clientFile('css', 'session-row-menu.css');

const groupsRules = rules(groupsCss);
const sidebarRules = rules(sidebarCss);
const rowMenuRules = rules(rowMenuCss);

function zIndexOf(ruleList, selector) {
    const hits = bySelector(ruleList, selector);
    assert.ok(hits.length > 0, `${selector} rule not found`);
    const value = decl(hits[0].body, 'z-index');
    assert.ok(value !== null, `${selector} should declare z-index`);
    const n = Number(value);
    assert.ok(Number.isFinite(n), `${selector} z-index (${value}) should be numeric`);
    return n;
}

test('.session-sidebar-group-menu paints above .session-sidebar-panel', () => {
    const menuZ = zIndexOf(groupsRules, '.session-sidebar-group-menu');
    const panelZ = zIndexOf(sidebarRules, '.session-sidebar-panel');
    assert.ok(menuZ > panelZ,
        `group menu z-index (${menuZ}) must exceed the sidebar panel's `
        + `(${panelZ}), or the menu paints behind the open sidebar`);
});

test('.session-sidebar-group-menu matches its row-level sibling, .session-row-menu', () => {
    const menuZ = zIndexOf(groupsRules, '.session-sidebar-group-menu');
    const rowMenuZ = zIndexOf(rowMenuRules, '.session-row-menu');
    assert.equal(menuZ, rowMenuZ,
        'the group menu and the row kebab menu are never open at the same '
        + 'time (each keeps a single-slot "open menu" reference), so they '
        + 'can safely share a z-index layer');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
