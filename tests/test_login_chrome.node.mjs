
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT = path.join(__dirname, '..', 'client');

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

function client(rel) {
    return fs.readFileSync(path.join(CLIENT, rel), 'utf8');
}

function loadScreenChrome() {
    const classes = new Set();
    const body = {
        dataset: {},
        classList: {
            toggle(name, on) { on ? classes.add(name) : classes.delete(name); },
            contains(name) { return classes.has(name); }
        }
    };
    const sandbox = {
        window: {},
        document: { body },
        console: { log() {} }
    };
    sandbox.window.document = sandbox.document;
    vm.createContext(sandbox);
    vm.runInContext(client('js/screen-chrome.js'), sandbox);
    return { ScreenChrome: sandbox.window.ScreenChrome, body };
}


test('the authenticated marker is ABSENT by default - fail closed', () => {
    const { body } = loadScreenChrome();
    assert.equal(body.classList.contains('is-authenticated'), false,
        'merely loading the module must not assert authentication');
});

test('only launchpad and terminal are authenticated screens', () => {
    const { ScreenChrome } = loadScreenChrome();
    assert.equal(
        Array.prototype.slice.call(ScreenChrome.AUTHENTICATED_SCREENS)
            .sort().join(','),
        'launchpad,terminal');
});

test('apply() marks the authenticated screens and clears auth', () => {
    const { ScreenChrome, body } = loadScreenChrome();
    ScreenChrome.apply('launchpad');
    assert.equal(body.classList.contains('is-authenticated'), true);
    assert.equal(body.dataset.screen, 'launchpad');

    ScreenChrome.apply('terminal');
    assert.equal(body.classList.contains('is-authenticated'), true);

    ScreenChrome.apply('auth');
    assert.equal(body.classList.contains('is-authenticated'), false,
        'the login screen must clear the marker, not merely not set it');
    assert.equal(body.dataset.screen, 'auth');
});

test('an UNKNOWN screen name is treated as unauthenticated', () => {
    const { ScreenChrome, body } = loadScreenChrome();
    ScreenChrome.apply('launchpad');
    for (const junk of ['', 'setup', undefined, null, 'AUTH']) {
        ScreenChrome.apply(junk);
        assert.equal(body.classList.contains('is-authenticated'), false,
            `apply(${JSON.stringify(junk)}) must not assert authentication`);
    }
});


test('the header gate addresses a CONTAINER, never a list of ids', () => {
    const css = client('css/screen-chrome.css');
    assert.match(
        css,
        /body:not\(\.is-authenticated\)\s+\.header\s+\.controls\s*>\s*\*:not\(\[data-show-on-auth\]\)\s*\{[^}]*display:\s*none\s*!important/,
        'the whole point is that a NEW control in .controls is covered ' +
        'with no code written. A selector listing ids would restore the ' +
        'exact failure mode this branch removed.'
    );
});

test('the floating-chrome gate is an opt-in token, and is !important', () => {
    const css = client('css/screen-chrome.css');
    assert.match(
        css,
        /body:not\(\.is-authenticated\)\s+\[data-auth-only\]\s*\{[^}]*display:\s*none\s*!important/,
        '#slash-commands-btn is shown by an inline style.display, so a ' +
        'non-important rule would lose to it - and that button is the ' +
        'one the user actually reported.'
    );
});

test('the gate stylesheet is linked from index.html', () => {
    assert.match(client('index.html'),
        /<link rel="stylesheet" href="\/static\/css\/screen-chrome\.css"/,
        'an unlinked stylesheet gates nothing');
});


test('showAuth() no longer carries a per-button hide list', () => {
    const app = client('js/app.js');
    const start = app.indexOf('    showAuth() {');
    assert.ok(start > 0, 'showAuth() not found');
    const body = app.slice(start, app.indexOf('\n    }', start))
        .split('\n').filter((l) => !/^\s*(\/\/|\*|\/\*)/.test(l)).join('\n');
    assert.doesNotMatch(body, /classList\.add\('hidden'\)/,
        'naming the controls to hide, one line each, IS the defect. ' +
        'Every control not on that list rendered on the login screen.');
    assert.match(body, /ScreenChrome\.apply\('auth'\)/);
});

test('every screen transition stamps the marker', () => {
    const app = client('js/app.js') + client('js/app-screen-entry.js');
    for (const screen of ['auth', 'launchpad', 'terminal']) {
        assert.ok(app.includes(`ScreenChrome.apply('${screen}')`),
            `no ScreenChrome.apply('${screen}') in app.js`);
    }
    const assigns = (app.match(/(?:this|app)\.currentScreen = '/g) || []).length;
    const stamps = (app.match(/ScreenChrome\.apply\('/g) || []).length;
    assert.equal(stamps, assigns,
        `${assigns} screen assignments but ${stamps} marker stamps`);
});

test('screen-chrome.js loads before app.js', () => {
    const html = client('index.html');
    const gate = html.indexOf('/static/js/screen-chrome.js');
    const app = html.indexOf('/static/js/app.js');
    assert.ok(gate > 0 && app > 0, 'both script tags must exist');
    assert.ok(gate < app, 'app.js calls ScreenChrome.apply() during boot');
});


test('the body-level floating controls declare data-auth-only', () => {
    assert.match(client('index.html'),
        /id="session-sidebar-toggle"[\s\S]{0,120}data-auth-only/);
});

test('THE LEAK IS GONE BY CONSTRUCTION: no floating control on <body>', () => {
    for (const f of ['js/slash-commands.js', 'js/dpad.js']) {
        assert.ok(!/document\.body\.appendChild/.test(client(f)),
            `${f} must not append a control to <body> any more`);
    }
    const bar = client('js/terminal-key-bar.js');
    assert.ok(bar.includes("getElementById(HOST_ID)"),
        'the key bar mounts into a screen, not onto <body>');
    assert.match(bar, /var HOST_ID = 'terminal-screen';/);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures ? 1 : 0);
