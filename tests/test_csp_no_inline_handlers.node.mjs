
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');

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

const INLINE_HANDLER = /\son[a-z]{2,24}\s*=\s*["'][^"']*["']/gi;

function shippedHtmlFiles() {
    const out = [];
    const walk = (dir) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (entry.name === 'node_modules' || entry.name.startsWith('.')) continue;
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) walk(full);
            else if (entry.name.endsWith('.html')) out.push(full);
        }
    };
    walk(path.join(ROOT, 'client'));
    return out;
}

test('client/index.html exists and is non-trivial', () => {
    const idx = path.join(ROOT, 'client', 'index.html');
    assert.ok(fs.existsSync(idx), 'client/index.html is missing');
    assert.ok(fs.readFileSync(idx, 'utf8').length > 5000,
        'client/index.html is suspiciously small - is this the real file?');
});

test('the CSP that makes this matter is still in force', () => {
    const hdrs = fs.readFileSync(
        path.join(ROOT, 'src', 'security_headers.py'), 'utf8');
    assert.ok(/\("script-src",\s*"'self'"\)/.test(hdrs),
        "src/security_headers.py no longer declares script-src 'self' - "
        + "this test's premise is gone");
    const table = (hdrs.match(/CSP_DIRECTIVES[\s\S]*?^\)/m) || [''])[0];
    assert.ok(table.includes('script-src'),
        'could not locate the CSP_DIRECTIVES table to check');
    assert.ok(!/unsafe-inline/.test(table.split('style-src')[0]),
        "script-src now allows 'unsafe-inline' - that needs its own argument");
    assert.ok(!/unsafe-hashes/.test(table),
        "'unsafe-hashes' would make inline event handlers legal again");

    const main = fs.readFileSync(path.join(ROOT, 'src', 'main.py'), 'utf8');
    assert.ok(/from\s+src\.security_headers\s+import\s+stamp_security_headers/
        .test(main), 'src/main.py no longer imports stamp_security_headers');
    assert.ok(/stamp_security_headers\(\s*response\.headers/.test(main),
        'src/main.py no longer stamps the security headers onto responses');
});

test('the static test server serves the app policy, not its own copy', () => {
    const lib = fs.readFileSync(
        path.join(ROOT, 'scripts', 'lib_csp_static_server.py'), 'utf8');
    assert.ok(/from\s+src\.security_headers\s+import/.test(lib),
        'the static test server no longer imports the app security headers');
    assert.ok(/build_csp\(/.test(lib),
        'the static test server no longer renders the policy via build_csp()');
});

test('the scanner finds files to scan', () => {
    const files = shippedHtmlFiles();
    assert.ok(files.length > 0, 'no shipped .html files found - the scan is vacuous');
});

test('the scanner actually detects an inline handler (positive control)', () => {
    const sample = '<button onclick="App.logout()" id="logoutBtn"></button>';
    assert.ok(new RegExp(INLINE_HANDLER.source, 'i').test(sample),
        'the detector does not match a known-bad inline handler');
    const clean = '<button id="logoutBtn" data-tooltip="Logout"></button>';
    assert.ok(!new RegExp(INLINE_HANDLER.source, 'i').test(clean),
        'the detector fires on markup that carries no handler');
});

test('no shipped HTML carries an inline event handler', () => {
    const offenders = [];
    for (const file of shippedHtmlFiles()) {
        const text = fs.readFileSync(file, 'utf8');
        text.split('\n').forEach((line, i) => {
            const code = line.replace(/<!--[\s\S]*?-->/g, '');
            const hits = code.match(new RegExp(INLINE_HANDLER.source, 'gi'));
            if (hits) {
                offenders.push(
                    `${path.relative(ROOT, file)}:${i + 1}  ${hits.join(' ')}`);
            }
        });
    }
    assert.deepEqual(offenders, [],
        "inline event handlers are dead under `script-src 'self'` - the "
        + 'browser refuses to run them and reports nothing. Wire these with '
        + 'addEventListener in the owning module instead:\n  '
        + offenders.join('\n  '));
});

test('#logoutBtn is wired in app.js, not in markup', () => {
    const app = fs.readFileSync(
        path.join(ROOT, 'client', 'js', 'app.js'), 'utf8');
    assert.ok(/this\.logoutBtn\s*\.addEventListener\(\s*['"]click['"]/.test(app),
        'app.js does not attach a click listener to this.logoutBtn');
    assert.ok(/this\.logoutBtn\s*=\s*document\.getElementById\(\s*['"]logoutBtn['"]/
        .test(app), 'app.js does not resolve #logoutBtn');
});

function clientJsFiles() {
    const out = [];
    const walk = (dir) => {
        for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
            if (entry.name === 'node_modules' || entry.name === 'vendor'
                || entry.name.startsWith('.')) continue;
            const full = path.join(dir, entry.name);
            if (entry.isDirectory()) walk(full);
            else if (entry.name.endsWith('.js')) out.push(full);
        }
    };
    walk(path.join(ROOT, 'client'));
    return out;
}

function stripJsComments(text) {
    return text
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/^\s*\/\/.*$/gm, '');
}

test('the client JS scanner finds files to scan', () => {
    assert.ok(clientJsFiles().length > 0,
        'no client .js files found - the scan is vacuous');
});

test('the client JS scanner detects an emitted handler (positive control)', () => {
    const sample = 'el.innerHTML = `<button onclick="App.logout()">x</button>`;';
    assert.ok(new RegExp(INLINE_HANDLER.source, 'i').test(sample),
        'the detector does not match a handler emitted from JS');
});

test('no client JS emits markup carrying an inline event handler', () => {
    const offenders = [];
    for (const file of clientJsFiles()) {
        const code = stripJsComments(fs.readFileSync(file, 'utf8'));
        code.split('\n').forEach((line, i) => {
            const hits = line.match(new RegExp(INLINE_HANDLER.source, 'gi'));
            if (hits) {
                offenders.push(
                    `${path.relative(ROOT, file)}:${i + 1}  ${hits.join(' ')}`);
            }
        });
    }
    assert.deepEqual(offenders, [],
        'markup written from JS is subject to the same CSP as markup in a '
        + '.html file - an inline handler here is just as dead, and the HTML '
        + 'scan cannot see it:\n  ' + offenders.join('\n  '));
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
