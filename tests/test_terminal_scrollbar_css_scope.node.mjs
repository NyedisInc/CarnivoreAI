
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');
const css = fs.readFileSync(path.join(repoRoot, 'client', 'css', 'styles.css'), 'utf8');
const indexHtml = fs.readFileSync(path.join(repoRoot, 'client', 'index.html'), 'utf8');
const cellSvelte = fs.readFileSync(
    path.join(repoRoot, 'web', 'src', 'opscenter', 'cells', 'terminal-viewer', 'Cell.svelte'),
    'utf8'
);

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

test('the scrollbar-hiding rules are no longer scoped to the #terminal id', () => {
    assert.equal(
        css.includes('#terminal .xterm-viewport {'),
        false,
        'expected the id-scoped scrollbar rule to be gone'
    );
    assert.equal(css.includes('#terminal .xterm-viewport::-webkit-scrollbar'), false);
});

test('the scrollbar-hiding rules are scoped to a class instead, and the block is not duplicated', () => {
    const overflowRuleMatches = css.match(/\.xterm-host \.xterm-viewport\s*\{[^}]*overflow-y:\s*scroll[^}]*\}/g);
    assert.ok(overflowRuleMatches, 'expected a `.xterm-host .xterm-viewport` rule setting overflow-y: scroll');
    assert.equal(overflowRuleMatches.length, 1, 'the rule block must be moved once, not duplicated');

    const webkitRuleMatches = css.match(/\.xterm-host \.xterm-viewport::-webkit-scrollbar\s*\{[^}]*display:\s*none[^}]*\}/g);
    assert.ok(webkitRuleMatches, 'expected a `.xterm-host .xterm-viewport::-webkit-scrollbar` rule');
    assert.equal(webkitRuleMatches.length, 1);
});

test('the main terminal\'s own div carries the shared class', () => {
    assert.match(
        indexHtml,
        /<div id="terminal" class="xterm-host">/,
        'expected #terminal to carry class="xterm-host" so it still matches the moved rule'
    );
});

test('a viewer cell\'s stage carries the shared class', () => {
    assert.match(
        cellSvelte,
        /class="oc-tv-stage xterm-host"/,
        'expected the cell\'s stage div, the element term.open() is called on, to carry class="xterm-host"'
    );
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
