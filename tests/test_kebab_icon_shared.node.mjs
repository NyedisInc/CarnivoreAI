// Exits 0 and prints "ALL PASS" on success; exits 1 otherwise.

import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function clientJs(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'js', name), 'utf8');
}

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

const HEADER_GLYPH_BEFORE_EXTRACTION =
    '<svg width="20" height="20" viewBox="0 0 16 16" fill="none" aria-hidden="true">'
    + '<circle cx="8" cy="3" r="2" fill="currentColor"/>'
    + '<circle cx="8" cy="8" r="2" fill="currentColor"/>'
    + '<circle cx="8" cy="13" r="2" fill="currentColor"/>'
    + '</svg>';

const context = { window: {}, console: { log() {} } };
context.window.window = context.window;
vm.createContext(context);
vm.runInContext(clientJs('kebab-icon.js'), context);
const KebabIcon = context.window.KebabIcon;

test('the shared glyph is byte-identical to the header s own, at the header s size', () => {
    assert.equal(KebabIcon.DEFAULT_SIZE, 20, 'the header renders at 20px');
    assert.equal(KebabIcon.svg(), HEADER_GLYPH_BEFORE_EXTRACTION);
    assert.equal(KebabIcon.svg(20), HEADER_GLYPH_BEFORE_EXTRACTION);
});

test('a smaller rendering scales the SAME dots, it does not thin them', () => {
    const small = KebabIcon.svg(16);
    assert.ok(small.includes('width="16" height="16"'));
    assert.ok(small.includes('viewBox="0 0 16 16"'), 'the 16-unit viewBox is fixed');
    assert.equal((small.match(/r="2"/g) || []).length, 3, 'three r=2 dots, always');
});

test('a bad size falls back to the header size rather than rendering nothing', () => {
    for (const bad of [undefined, null, 0, -4, '20', NaN]) {
        assert.equal(KebabIcon.svg(bad), HEADER_GLYPH_BEFORE_EXTRACTION,
            `size ${String(bad)} must fall back, not emit a 0px icon`);
    }
});

test('there is exactly ONE definition of the mark in the client', () => {
    const dir = path.join(__dirname, '..', 'client', 'js');
    const offenders = [];
    for (const name of fs.readdirSync(dir)) {
        if (!name.endsWith('.js') || name === 'kebab-icon.js') continue;
        const src = fs.readFileSync(path.join(dir, name), 'utf8');
        if (src.includes('<circle cx="8" cy="13"')) offenders.push(name);
    }
    assert.deepEqual(offenders, [],
        `these files draw their own kebab instead of calling KebabIcon: ${offenders}`);
});

test('both consumers actually call the shared builder', () => {
    assert.ok(clientJs('header-menu.js').includes('window.KebabIcon.svg('),
        'the header overflow must render the shared mark');
    const row = fs.readFileSync(path.join(__dirname, '..', 'web', 'src', 'lib', 'item-menu', 'row-context.ts'), 'utf8');
    assert.ok(/const kebab = g\(\)\.KebabIcon;/.test(row) && row.includes('kebab.svg('),
        'the sidebar row kebab must render the shared mark');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
