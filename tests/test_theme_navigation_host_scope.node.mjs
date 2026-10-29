
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');

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

function load(withKeyModule = true) {
    const calls = { scopes: [], applied: [], terminalScopes: [] };
    const sandbox = {
        console: { log() {}, warn() {}, error() {} },
        setTimeout: () => 0,
        clearTimeout() {},
    };
    sandbox.window = sandbox;
    vm.createContext(sandbox);

    sandbox.Themes = {
        getStoredThemeId() { return 'claude'; },
        clearSession() {},
        setActiveSession(n) { calls.scopes.push(n); },
        applyTheme(id, opt) { calls.applied.push({ id, opt: opt || {} }); return true; },
        applySessionScope(ctx) { calls.terminalScopes.push(ctx || {}); },
    };

    if (withKeyModule) {
        vm.runInContext(fs.readFileSync(path.join(ROOT, 'client', 'js', 'session-key.js'), 'utf8'),
            sandbox);
    }
    const source = fs.readFileSync(path.join(ROOT, 'client', 'js', 'theme-navigation.js'), 'utf8');
    vm.runInContext(source, sandbox);
    return { nav: sandbox.window.ThemeNavigation, calls };
}

test('a local session (host_key: "local") enters scope by its name', () => {
    const { nav, calls } = load();
    nav.applyForSession({ host_key: 'local', pinned_theme: 'matrix' }, 'cloude_a');
    assert.deepEqual(calls.scopes, ['cloude_a']);
});

test('a wrapper with no host_key at all (a pre-#162 server) still enters scope', () => {
    const { nav, calls } = load();
    nav.applyForSession({ pinned_theme: 'matrix' }, 'cloude_a');
    assert.deepEqual(calls.scopes, ['cloude_a']);
});

test('a remote session enters scope under its own remote:<host>:<name> key', () => {
    const { nav, calls } = load();
    nav.applyForSession({ host_key: 'hosta', pinned_theme: 'matrix' }, 'cloude_a');
    assert.deepEqual(calls.scopes, ['remote:hosta:cloude_a']);
});

test('a remote session still paints the global page theme, and its own pin on its terminal', () => {
    const { nav, calls } = load();
    nav.applyForSession({ host_key: 'hosta', pinned_theme: 'matrix' }, 'cloude_a');
    assert.equal(calls.applied.length, 1);
    assert.equal(calls.applied[0].id, 'claude');
    assert.equal(calls.terminalScopes[0].pinnedTheme, 'matrix');
});

test('a same-named local and remote session never share a scope key', () => {
    const { nav, calls } = load();
    nav.applyForSession({ host_key: 'local' }, 'cloude_a');
    nav.applyForSession({ host_key: 'hosta' }, 'cloude_a');
    nav.applyForSession({ host_key: 'nas' }, 'cloude_a');
    assert.deepEqual(calls.scopes, ['cloude_a', 'remote:hosta:cloude_a', 'remote:nas:cloude_a']);
});

test('FAIL CLOSED: without the key module a remote session never enters scope', () => {
    const { nav, calls } = load(false);
    nav.applyForSession({ host_key: 'hosta', pinned_theme: 'matrix' }, 'cloude_a');
    nav.applyForSession({ host_key: 'local' }, 'cloude_a');
    assert.deepEqual(calls.scopes, [null, 'cloude_a']);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) {
    console.error('FAILED');
    process.exit(1);
}
console.log('ALL PASS');
