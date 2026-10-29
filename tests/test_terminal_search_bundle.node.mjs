// agrees with whatever it was built to agree with.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';

import { installCloudeWeb } from './helpers/cloude-web-sandbox.mjs';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

function loadBundle() {
    const context = vm.createContext({
        console,
        document: {
            getElementById: () => null,
            querySelector: () => null,
            addEventListener: () => {},
            removeEventListener: () => {},
        },
    });
    return installCloudeWeb(context);
}

test('the bundle publishes the three session-search entry points', () => {
    const web = loadBundle();
    for (const name of [
        'mountTerminalSearch',
        'openTerminalSearch',
        'toggleTerminalSearch',
        'terminalSearchIsOpen',
        'unmountTerminalSearch',
    ]) {
        assert.equal(typeof web[name], 'function', `CloudeWeb.${name} must be a function`);
    }
});

test('on a page with no terminal container the mount is a silent no-op', () => {
    const web = loadBundle();
    assert.equal(web.mountTerminalSearch(), null);
    assert.equal(web.terminalSearchIsOpen(), false);
    assert.doesNotThrow(() => web.openTerminalSearch());
    assert.doesNotThrow(() => web.toggleTerminalSearch());
});

test('index.html no longer loads the four files the port deleted', () => {
    const html = read('client/index.html');
    for (const gone of [
        'terminal-search.js',
        'terminal-search-chrome.js',
        'terminal-search-keys.js',
        'terminal-prompt-rail.js',
        'terminal-search.css',
    ]) {
        assert.ok(
            !html.includes(`/static/js/${gone}`) && !html.includes(`/static/css/${gone}`),
            `${gone} is still loaded by client/index.html`,
        );
        assert.ok(
            !fs.existsSync(path.join(ROOT, 'client', 'js', gone)),
            `client/js/${gone} should have been deleted with its script tag`,
        );
    }
});

test('the three framework-free modules and the add-on are still loaded', () => {
    const html = read('client/index.html');
    for (const kept of [
        '/static/js/terminal-prompt-scan.js',
        '/static/js/terminal-history-load.js',
        '/static/js/terminal-search-engine.js',
        '/static/vendor/xterm/xterm-addon-search.js',
    ]) {
        assert.ok(html.includes(kept), `${kept} must still be loaded`);
    }
});

test('the deep-dive button and its module are gone (Alex (example-owner), 2026-09-26)', () => {
    const html = read('client/index.html');
    assert.ok(
        !html.includes('/static/js/terminal-search-deep-dive.js'),
        'terminal-search-deep-dive.js is still loaded by client/index.html',
    );
    assert.ok(
        !fs.existsSync(path.join(ROOT, 'client', 'js', 'terminal-search-deep-dive.js')),
        'client/js/terminal-search-deep-dive.js should have been deleted with its script tag',
    );
});

test('the terminal container carries the id the one mount path addresses', () => {
    const html = read('client/index.html');
    assert.match(html, /class="terminal-container" id="terminal-container"/);
});

test('the header button is still there, still wired in JS and not in markup', () => {
    const html = read('client/index.html');
    const at = html.indexOf('id="terminalSearchBtn"');
    assert.ok(at > -1, 'the header button must exist in the shell');
    const tag = html.slice(html.lastIndexOf('<button', at), html.indexOf('>', at) + 1);
    assert.ok(
        !/onclick/.test(tag),
        'src/main.py stamps script-src self; an inline handler is silently dead',
    );
    assert.match(tag, /aria-label="search session"/);
    assert.match(tag, /title="search \(Cmd\+F\)"/, 'the hotkey must be advertised');
    assert.match(tag, /class="btn-icon"/, 'the box comes from the header, not from us');
});

test('the tools menu leaves search to the header and keyboard shortcut', () => {
    const src = read('client/js/terminal-tools-menu.js');
    assert.ok(!src.includes("'toolSearch'"));
    assert.ok(!src.includes('web.openTerminalSearch('));
    assert.ok(
        !src.includes('window.TerminalSearch'),
        'window.TerminalSearch no longer exists; the row must not reach for it',
    );
});

test('the emitted stylesheet still carries the rules the panel cannot scope', () => {
    const css = read('client/dist/app.css');
    assert.ok(css.includes('--terminal-search-match-bg:'), 'the decoration colours must ship');
    assert.ok(css.includes('#terminalSearchBtn'), 'the header trigger scoping must ship');
    assert.ok(
        css.includes('body:has(#terminal-screen.active) #terminalSearchBtn'),
        'the trigger must be allowed on the terminal screen, not inside it',
    );
    assert.ok(
        !css.includes('terminal-search-toast-top') && !css.includes('terminal-prompt-toast-top'),
        'no pane may offset the viewport-level toast stack (#1220)',
    );
    assert.match(
        css,
        /\.terminal-prompt-rail\[hidden\][^{]*\{[^}]*display:\s*none\s*!important/,
        'the rail hides with el.hidden, and [hidden] in the UA sheet loses to any author display',
    );
});

const LINE_BUDGET = 1000;

test('every file the port added stays under the line budget', () => {
    const dir = path.join(ROOT, 'web', 'src', 'lib', 'terminal-search');
    for (const name of fs.readdirSync(dir)) {
        const lines = fs.readFileSync(path.join(dir, name), 'utf8').split('\n').length;
        assert.ok(lines <= LINE_BUDGET, `${name} is ${lines} lines, over the ${LINE_BUDGET} budget`);
    }
});
