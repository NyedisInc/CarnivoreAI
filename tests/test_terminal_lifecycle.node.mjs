
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

const lifecycleSrc = read('client/js/terminal-lifecycle.js');
const terminalSrc = read('client/js/terminal.js');
const indexHtml = read('client/index.html');
const hostSrc = read('web/src/lib/terminal-search/search-host.ts');

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

function sandbox(options = {}) {
    const events = [];
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    if (!options.noDispatch) {
        fakeWindow.dispatchEvent = (event) => {
            if (options.dispatchThrows) throw new Error('refused');
            events.push(event);
            return true;
        };
    }
    const context = {
        window: fakeWindow,
        console: { log() {}, warn() {}, error() {} },
    };
    if (!options.noCustomEvent) {
        context.CustomEvent = class CustomEvent {
            constructor(type, init) {
                this.type = type;
                this.detail = init && init.detail;
            }
        };
    }
    vm.createContext(context);
    vm.runInContext(lifecycleSrc, context, { filename: 'terminal-lifecycle.js' });
    return { api: context.window.TerminalLifecycle, events };
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('the module publishes announceCreated and the event name', () => {
    const { api } = sandbox();
    assert.ok(api, 'terminal-lifecycle.js must publish window.TerminalLifecycle');
    assert.equal(typeof api.announceCreated, 'function');
    assert.equal(api.TERMINAL_CREATED, 'terminal-created');
});

test('it sends exactly one window event, named terminal-created', () => {
    const { api, events } = sandbox();
    assert.equal(api.announceCreated({ id: 'term-a' }), true);
    assert.equal(events.length, 1);
    assert.equal(events[0].type, 'terminal-created');
});

test('the event carries the terminal that was just built', () => {
    const { api, events } = sandbox();
    const term = { id: 'term-a' };
    api.announceCreated(term);
    assert.equal(events[0].detail.term, term);
});

test('a REPLACEMENT is a creation: it announces every time', () => {
    const { api, events } = sandbox();
    api.announceCreated({ id: 'term-a' });
    api.announceCreated({ id: 'term-b' });
    assert.equal(events.length, 2);
    assert.equal(events[0].detail.term.id, 'term-a');
    assert.equal(events[1].detail.term.id, 'term-b');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('a dispatch that throws is swallowed and reported as false', () => {
    const { api } = sandbox({ dispatchThrows: true });
    let result;
    assert.doesNotThrow(() => { result = api.announceCreated({}); });
    assert.equal(result, false);
});

test('a realm with no CustomEvent refuses rather than throwing', () => {
    const { api, events } = sandbox({ noCustomEvent: true });
    assert.equal(api.announceCreated({}), false);
    assert.equal(events.length, 0);
});

test('a window that cannot dispatch refuses rather than throwing', () => {
    const { api, events } = sandbox({ noDispatch: true });
    assert.equal(api.announceCreated({}), false);
    assert.equal(events.length, 0);
});

test('NEGATIVE: the harness can go red - a working realm returns true', () => {
    // nothing at all
    const { api, events } = sandbox();
    assert.equal(api.announceCreated({}), true);
    assert.equal(events.length, 1);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('initTerminal() announces, and does it LAST', () => {
    const start = terminalSrc.indexOf('    initTerminal() {');
    assert.ok(start !== -1, 'initTerminal() must still exist');
    const end = terminalSrc.indexOf('\n    }\n', start);
    assert.ok(end !== -1, 'initTerminal() must still close');
    const body = terminalSrc.slice(start, end);
    const call = 'window.TerminalLifecycle.announceCreated(this.term)';
    assert.match(
        body,
        /^ {8}if \(window\.TerminalLifecycle\) window\.TerminalLifecycle\.announceCreated\(this\.term\);/m,
        'initTerminal() must announce the terminal it just built, guarded'
    );
    const after = body.slice(body.indexOf(call) + call.length);
    assert.doesNotMatch(after, /this\.term\.[a-zA-Z]/,
        'nothing may touch the terminal after the announcement');
});

test('terminal-lifecycle.js loads BEFORE terminal.js', () => {
    const mod = indexHtml.indexOf('/static/js/terminal-lifecycle.js');
    const term = indexHtml.indexOf('/static/js/terminal.js"');
    assert.ok(mod !== -1, 'index.html must load terminal-lifecycle.js');
    assert.ok(term !== -1, 'index.html must load terminal.js');
    assert.ok(mod < term, 'terminal-lifecycle.js must load before terminal.js');
});

test('the compiled tree subscribes to that exact event name', () => {
    const name = /'terminal-created'/;
    assert.match(lifecycleSrc, /TERMINAL_CREATED = 'terminal-created'/);
    assert.match(hostSrc, /TERMINAL_CREATED_EVENT = 'terminal-created'/);
    assert.match(hostSrc, name);
    assert.match(hostSrc, /addEventListener\(TERMINAL_CREATED_EVENT, listener\)/);
    assert.match(hostSrc, /removeEventListener\(TERMINAL_CREATED_EVENT, listener\)/);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
