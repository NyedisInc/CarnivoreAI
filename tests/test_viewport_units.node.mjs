
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CSS_DIR = path.join(__dirname, '..', 'client', 'css');

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

function cssFiles(dir) {
    const out = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) out.push(...cssFiles(full));
        else if (entry.name.endsWith('.css')) out.push(full);
    }
    return out;
}

function codeOf(line) {
    const trimmed = line.trim();
    if (trimmed.startsWith('*') || trimmed.startsWith('/*') || trimmed.startsWith('//')) {
        return '';
    }
    return line.split('/*')[0];
}

const RAW_VH = /\d+vh\b/;

test('every raw vh declaration is followed by its dvh twin', () => {
    const offenders = [];
    for (const file of cssFiles(CSS_DIR)) {
        const lines = fs.readFileSync(file, 'utf8').split('\n');
        for (let i = 0; i < lines.length; i++) {
            const code = codeOf(lines[i]);
            if (!RAW_VH.test(code)) continue;
            const expected = lines[i].replace(/(\d+)vh\b/g, '$1dvh');
            if (lines[i + 1] !== expected) {
                offenders.push(
                    `${path.relative(CSS_DIR, file)}:${i + 1}\n` +
                    `      got:  ${(lines[i + 1] || '<eof>').trim()}\n` +
                    `      want: ${expected.trim()}`);
            }
        }
    }
    assert.deepEqual(offenders, [],
        'raw vh without a dvh fallback line:\n  ' + offenders.join('\n  '));
});

test('the dvh line never comes first, or the fallback would win', () => {
    const offenders = [];
    for (const file of cssFiles(CSS_DIR)) {
        const lines = fs.readFileSync(file, 'utf8').split('\n');
        for (let i = 0; i < lines.length; i++) {
            const code = codeOf(lines[i]);
            if (!/\d+dvh\b/.test(code)) continue;
            const previous = lines[i - 1];
            const expected = lines[i].replace(/(\d+)dvh\b/g, '$1vh');
            if (previous !== expected) {
                offenders.push(`${path.relative(CSS_DIR, file)}:${i + 1}`);
            }
        }
    }
    assert.deepEqual(offenders, [],
        'dvh declarations missing a preceding vh fallback: ' + offenders.join(', '));
});

test('the header menu cap fits below the header on a 390x844 phone', () => {
    const src = fs.readFileSync(path.join(CSS_DIR, 'header-menu.css'), 'utf8');
    const match = src.match(/max-height:\s*calc\(100dvh - (\d+)px\);/);
    assert.ok(match, 'header-menu.css must cap the panel in dvh');
    const inset = Number(match[1]);
    const visibleViewport = 699;
    const headerHeight = 58;
    const cap = visibleViewport - inset;
    assert.ok(cap <= visibleViewport - headerHeight,
        `cap ${cap}px must fit in the ${visibleViewport - headerHeight}px below the header`);
});

test('body keeps a definite height with a dvh fallback pair', () => {
    const src = fs.readFileSync(path.join(CSS_DIR, 'styles.css'), 'utf8');
    assert.match(src, /height:\s*100vh;\n\s*height:\s*100dvh;/,
        'body must declare height: 100vh then height: 100dvh');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
