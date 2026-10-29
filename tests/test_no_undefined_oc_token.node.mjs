// real.

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

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
        console.error(`  ${err && err.message ? err.message : err}`);
    }
}

const DECL_RE = /--oc-[A-Za-z0-9-]+(?=\s*:)/g;
const STYLE_DIRECTIVE_RE = /style:(--oc-[A-Za-z0-9-]+)\s*=/g;
const RUNTIME_PROP_RE = /['"](--oc-[A-Za-z0-9-]+)['"]/g;
const USE_RE = /var\(\s*(--oc-[A-Za-z0-9-]+)\s*[,)]/g;

function stripBlockComments(text) {
    return text.replace(/\/\*[\s\S]*?\*\//g, (m) => '\n'.repeat((m.match(/\n/g) || []).length));
}

function scannedFiles() {
    const out = [];
    const exts = ['.css', '.svelte', '.ts', '.json'];
    const skipDirs = new Set(['node_modules', 'dist', 'vendor', 'widget-harness-build']);
    const walk = (dir) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (skipDirs.has(entry.name) || entry.name.startsWith('.')) continue;
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) walk(full);
            else if (exts.some((e) => entry.name.endsWith(e))) out.push(full);
        }
    };
    walk(path.join(ROOT, 'client'));
    walk(path.join(ROOT, 'web', 'src'));
    return out;
}

function scan(files) {
    const declared = new Set();
    const uses = [];
    for (const file of files) {
        const raw = fs.readFileSync(file, 'utf8');
        const code = stripBlockComments(raw);
        const relFile = path.relative(ROOT, file);
        const lines = code.split('\n');
        lines.forEach((line, i) => {
            for (const m of line.matchAll(DECL_RE)) declared.add(m[0]);
            for (const m of line.matchAll(STYLE_DIRECTIVE_RE)) declared.add(m[1]);
            if (file.endsWith('.ts') && !file.endsWith('.test.ts')) {
                for (const m of line.matchAll(RUNTIME_PROP_RE)) declared.add(m[1]);
            }
            for (const m of line.matchAll(USE_RE)) {
                uses.push({
                    token: m[1],
                    file: relFile,
                    line: i + 1,
                    snippet: line.trim(),
                });
            }
        });
    }
    return { declared, uses };
}

test('the scanner finds files to scan', () => {
    assert.ok(scannedFiles().length > 0, 'no client/web files found - the scan is vacuous');
});

test('the guard can actually fail (positive control)', () => {
    const tmpDir = fs.mkdtempSync(path.join(ROOT, '.tmp_oc_token_guard_proof_'));
    try {
        fs.writeFileSync(
            path.join(tmpDir, 'planted.css'),
            '.planted { color: var(--oc-not-real, #a970ff); }\n',
        );
        const { declared, uses } = scan([path.join(tmpDir, 'planted.css')]);
        const undefinedUses = uses.filter((u) => !declared.has(u.token));
        assert.equal(undefinedUses.length, 1,
            `expected exactly one undefined use, scanner found ${undefinedUses.length}`);
        assert.equal(undefinedUses[0].token, '--oc-not-real');
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
    }
});

test('a declared-and-used token is not flagged (negative control)', () => {
    const tmpDir = fs.mkdtempSync(path.join(ROOT, '.tmp_oc_token_guard_proof_'));
    try {
        fs.writeFileSync(
            path.join(tmpDir, 'safe.css'),
            ':root { --oc-planted-safe: #fff; }\n.safe { color: var(--oc-planted-safe); }\n',
        );
        const { declared, uses } = scan([path.join(tmpDir, 'safe.css')]);
        const undefinedUses = uses.filter((u) => !declared.has(u.token));
        assert.deepEqual(undefinedUses, []);
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
    }
});

test('a Svelte style:--oc-x={...} directive counts as a declaration (negative control)', () => {
    const tmpDir = fs.mkdtempSync(path.join(ROOT, '.tmp_oc_token_guard_proof_'));
    try {
        fs.writeFileSync(
            path.join(tmpDir, 'planted.svelte'),
            '<div style:--oc-planted-inline={value}></div>\n'
            + '<style>.x { color: var(--oc-planted-inline); }</style>\n',
        );
        const { declared, uses } = scan([path.join(tmpDir, 'planted.svelte')]);
        const undefinedUses = uses.filter((u) => !declared.has(u.token));
        assert.deepEqual(undefinedUses, []);
    } finally {
        fs.rmSync(tmpDir, { recursive: true, force: true });
    }
});

test('every var(--oc-*) reference across client/ and web/src/ resolves to a real declaration', () => {
    const { declared, uses } = scan(scannedFiles());
    const undefinedUses = uses.filter((u) => !declared.has(u.token));
    assert.deepEqual(
        undefinedUses.map((u) => `${u.file}:${u.line}  ${u.snippet}`),
        [],
        'undefined --oc-* token reference(s) - each always falls through to its '
        + 'fallback value (or nothing) on every theme, which is the same class of '
        + 'bug as issue #905 (--oc-purple, never declared, always painted its '
        + 'hardcoded hex fallback). Point the reference at a real, declared token '
        + 'in web/src/opscenter/tokens.css instead of inventing a new hardcoded '
        + 'fallback, or declare the token there (re-derived from the theme '
        + 'manifest like every other --oc-* token) if it is genuinely new:\n  '
        + undefinedUses.map((u) => `${u.file}:${u.line}  ${u.snippet}`).join('\n  '),
    );
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
