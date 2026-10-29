
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { TerminalProvider } from '../web/src/lib/terminal-provider/provider.ts';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');
const src = fs.readFileSync(path.join(CLIENT_JS, 'terminal-select-scrolled.js'), 'utf8');

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

class FakeMouseEvent {
    constructor(type, init) {
        this.type = type;
        Object.assign(this, init);
    }
}

function loadModule(state) {
    const dispatched = [];
    const screenEl = {
        dispatchEvent(ev) { dispatched.push(ev); return true; },
    };
    const term = {
        options: { macOptionClickForcesSelection: false },
        _core: { coreMouseService: { areMouseEventsActive: state.mouseActive } },
        element: { querySelector: (sel) => (sel === '.xterm-screen' ? screenEl : null) },
    };
    const windowObj = {
        TerminalScroll: { isPinnedToBottom: () => state.pinned },
    };
    if (state.altScreenState !== undefined) {
        windowObj.AltScreenScroll = { detectState: () => state.altScreenState };
    }
    const sandbox = {
        window: windowObj,
        console: { warn() {}, log() {} },
        MouseEvent: FakeMouseEvent,
    };
    sandbox.globalThis = sandbox;
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    return { api: sandbox.window.TerminalSelectScrolled, term, screenEl, dispatched };
}

function realMouseDown(overrides) {
    let prevented = false;
    let stopped = false;
    return Object.assign({
        button: 0,
        buttons: 1,
        detail: 1,
        clientX: 42,
        clientY: 77,
        preventDefault() { prevented = true; },
        stopPropagation() { stopped = true; },
        get defaultPrevented() { return prevented; },
        get propagationStopped() { return stopped; },
    }, overrides);
}


test('scrolled up + mouse tracking active: real mousedown is replaced', () => {
    const { api, term, dispatched } = loadModule({ pinned: false, mouseActive: true });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, true, 'the real report-triggering event must be cancelled');
    assert.equal(ev.propagationStopped, true, 'must not also reach xterm\'s own report-mode listener');
    assert.equal(dispatched.length, 1, 'exactly one synthetic mousedown must be dispatched');
    const synth = dispatched[0];
    assert.equal(synth.type, 'mousedown');
    assert.equal(synth.shiftKey, true, 'non-mac force-selection gate');
    assert.equal(synth.altKey, true, 'mac force-selection gate (with macOptionClickForcesSelection)');
    assert.equal(synth.clientX, 42);
    assert.equal(synth.clientY, 77);
});

test('at the live bottom: nothing is touched, the app stays in control', () => {
    const { api, term, dispatched } = loadModule({ pinned: true, mouseActive: true });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, false, 'a live-bottom click is a legitimate app interaction');
    assert.equal(dispatched.length, 0);
});


test('alternate screen, claude transcript view open: real mousedown is replaced', () => {
    const { api, term, dispatched } = loadModule({
        pinned: true, mouseActive: true, altScreenState: 'transcript',
    });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, true,
        'baseY===0 must not be read as "at the live bottom" once the alt screen is showing scrollback');
    assert.equal(dispatched.length, 1);
    assert.equal(dispatched[0].shiftKey, true);
});

test('alternate screen, claude at its live prompt: left alone', () => {
    const { api, term, dispatched } = loadModule({
        pinned: true, mouseActive: true, altScreenState: 'live',
    });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, false,
        'a click on claude\'s own live prompt frame is a legitimate app interaction');
    assert.equal(dispatched.length, 0);
});

test('alternate screen, unidentified program (vim, htop, ...): left alone', () => {
    const { api, term, dispatched } = loadModule({
        pinned: true, mouseActive: true, altScreenState: 'unknown',
    });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, false,
        'forcing local selection for every unidentified alt-screen program would break its own '
        + 'mouse handling (cursor placement, visual-mode select) even when it was never scrolled - '
        + 'altscreen-scroll.js\'s own contract is "unknown means do nothing"');
    assert.equal(dispatched.length, 0);
});

test('AltScreenScroll not loaded: fails closed to the pre-fix behaviour', () => {
    const { api, term, dispatched } = loadModule({ pinned: true, mouseActive: true });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, false,
        'no module to ask means no evidence of scrollback - must not intercept');
    assert.equal(dispatched.length, 0);
});

test('AltScreenScroll.detectState throwing: fails closed, does not crash the click', () => {
    const { api, term, dispatched } = loadModule({ pinned: true, mouseActive: true });
    term._forceDetectStateThrow = true;
    const sandboxWindow = { TerminalScroll: { isPinnedToBottom: () => true } };
    sandboxWindow.AltScreenScroll = { detectState() { throw new Error('buffer read failed'); } };
    const src = fs.readFileSync(path.join(CLIENT_JS, 'terminal-select-scrolled.js'), 'utf8');
    const dispatched2 = [];
    const screenEl2 = { dispatchEvent(ev) { dispatched2.push(ev); return true; } };
    const term2 = {
        options: { macOptionClickForcesSelection: false },
        _core: { coreMouseService: { areMouseEventsActive: true } },
        element: { querySelector: (sel) => (sel === '.xterm-screen' ? screenEl2 : null) },
    };
    const sandbox = {
        window: sandboxWindow,
        console: { warn() {}, log() {} },
        MouseEvent: FakeMouseEvent,
    };
    sandbox.globalThis = sandbox;
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    const ev = realMouseDown();
    assert.doesNotThrow(() => sandbox.window.TerminalSelectScrolled.handleMouseDown(term2, ev));
    assert.equal(ev.defaultPrevented, false, 'a throwing detectState must not intercept the click');
    assert.equal(dispatched2.length, 0);
});

test('mouse tracking off: the app never owned this gesture, nothing to fix', () => {
    const { api, term, dispatched } = loadModule({ pinned: false, mouseActive: false });
    const ev = realMouseDown();
    api.handleMouseDown(term, ev);
    assert.equal(ev.defaultPrevented, false,
        'xterm\'s own SelectionService already handles this correctly - see scenario A '
        + 'in the harness note below; touching it here would be pure risk for no gain');
    assert.equal(dispatched.length, 0);
});

test('a right or middle click is left alone even when scrolled up', () => {
    const { api, term, dispatched } = loadModule({ pinned: false, mouseActive: true });
    for (const button of [1, 2]) {
        const ev = realMouseDown({ button });
        api.handleMouseDown(term, ev);
        assert.equal(ev.defaultPrevented, false, `button ${button} must not be intercepted`);
    }
    assert.equal(dispatched.length, 0);
});


test('the mac force-selection option is restored after dispatch, not left on', () => {
    const { api, term } = loadModule({ pinned: false, mouseActive: true });
    term.options.macOptionClickForcesSelection = false;
    api.handleMouseDown(term, realMouseDown());
    assert.equal(term.options.macOptionClickForcesSelection, false,
        'a permanent flip would silently change the user\'s own option-click behaviour');
});

test('the option is flipped back even if it started true', () => {
    const { api, term } = loadModule({ pinned: false, mouseActive: true });
    term.options.macOptionClickForcesSelection = true;
    api.handleMouseDown(term, realMouseDown());
    assert.equal(term.options.macOptionClickForcesSelection, true);
});


test('an unreadable coreMouseService fails to the safe no-op side', () => {
    const { api, dispatched } = loadModule({ pinned: false, mouseActive: true });
    const brokenTerm = { options: {}, element: {} };
    const ev = realMouseDown();
    api.handleMouseDown(brokenTerm, ev);
    assert.equal(ev.defaultPrevented, false, 'must not intercept when it cannot even ask');
    assert.equal(dispatched.length, 0);
});

test('a missing .xterm-screen element is a no-op, not a throw', () => {
    const { api, term } = loadModule({ pinned: false, mouseActive: true });
    term.element.querySelector = () => null;
    assert.doesNotThrow(() => api.handleMouseDown(term, realMouseDown()));
});


test('terminal.js wires TerminalSelectScrolled from initTerminal', () => {
    const terminalSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8');
    assert.match(terminalSrc, /_applySelectWhileScrolled\s*\(\s*\)\s*\{/,
        'the hook method must exist');
    assert.match(terminalSrc, /this\._applySelectWhileScrolled\(\);/,
        'initTerminal must call it, same as _applyTouchSelection()');
    const defMatch = terminalSrc.match(/_applySelectWhileScrolled\(\)\s*\{/);
    assert.ok(defMatch, 'method definition not found');
    const at = defMatch.index;
    const body = terminalSrc.slice(at, at + 500);
    assert.match(body, /sel\.init\(/,
        'the hook must actually call TerminalSelectScrolled.init');
    assert.match(body, /const sel = this\._m\('TerminalSelectScrolled'\);\s*if\s*\(\s*sel\s*\)\s*sel\.init\(/,
        'the call must be guarded on the module being loaded, and on nothing else - '
        + 'a constant-false guard disables the whole feature while still reading as wired');
});

test('index.html loads terminal-select-scrolled.js after terminal-scroll.js, before terminal.js', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    const scroll = html.indexOf('terminal-scroll.js');
    const selectScrolled = html.indexOf('terminal-select-scrolled.js');
    const term = html.indexOf('/static/js/terminal.js');
    assert.notEqual(selectScrolled, -1, 'terminal-select-scrolled.js must be loaded');
    assert.ok(scroll < selectScrolled,
        'it reads window.TerminalScroll.isPinnedToBottom() and must load after it');
    assert.ok(selectScrolled < term,
        'terminal.js calls it from initTerminal() and must load after it');
});


function loadModuleReentrant(state) {
    const dispatched = [];
    const docEvents = [];
    const holder = {};
    const screenEl = {
        dispatchEvent(ev) {
            dispatched.push(ev);
            holder.api.handleMouseDown(holder.term, ev);
            return true;
        },
    };
    const term = {
        options: { macOptionClickForcesSelection: false },
        rows: 24,
        _core: { coreMouseService: { areMouseEventsActive: state.mouseActive } },
        element: { querySelector: (sel) => (sel === '.xterm-screen' ? screenEl : null) },
        hasSelection: () => !!state.hasSelection,
    };
    const windowObj = { TerminalScroll: { isPinnedToBottom: () => state.pinned } };
    if (state.altScreenState !== undefined) {
        windowObj.AltScreenScroll = { detectState: () => state.altScreenState };
    }
    const sandbox = {
        window: windowObj,
        document: { dispatchEvent(ev) { docEvents.push(ev); return true; } },
        console: { warn() {}, log() {} },
        MouseEvent: FakeMouseEvent,
    };
    sandbox.globalThis = sandbox;
    sandbox.TerminalProvider = TerminalProvider;
    vm.createContext(sandbox);
    vm.runInContext(src, sandbox);
    holder.api = sandbox.window.TerminalSelectScrolled;
    holder.term = term;
    return { api: holder.api, term, dispatched, docEvents };
}

function realMouseUp(overrides) {
    let stopped = false;
    return Object.assign({
        button: 0, buttons: 0, detail: 1, clientX: 42, clientY: 77,
        stopPropagation() { stopped = true; },
        get propagationStopped() { return stopped; },
    }, overrides);
}

function realMouseMove(overrides) {
    let stopped = false;
    return Object.assign({
        button: 0, buttons: 0, clientX: 100, clientY: 120,
        stopPropagation() { stopped = true; },
        get propagationStopped() { return stopped; },
    }, overrides);
}

test('DEFECT 1: the synthetic mousedown is dispatched EXACTLY once, not recursively', () => {
    const { api, term, dispatched } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript',
    });
    api.handleMouseDown(term, realMouseDown());
    assert.equal(dispatched.length, 1,
        'without the re-entrancy guard this recurses - measured at 44 synthetic events '
        + 'for one real click, with zero of them ever reaching xterm');
});

test('DEFECT 1: the replacement reaches xterm uncancelled', () => {
    const { api, term, dispatched } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript',
    });
    api.handleMouseDown(term, realMouseDown());
    const synth = dispatched[0];
    assert.equal(synth.propagationStopped, undefined,
        'the module must not call stopPropagation on its own replacement - doing so is '
        + 'exactly what stopped SelectionService from ever seeing the forced mousedown');
    assert.equal(synth.shiftKey, true);
    assert.equal(synth.altKey, true);
});

test('DEFECT 1: the guard is lowered again once dispatch returns', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript',
    });
    api.handleMouseDown(term, realMouseDown());
    assert.equal(api._isDispatching(), false,
        'a guard left raised would swallow every subsequent click');
});

test('DEFECT 2: the mouseup of a forced gesture is withheld from xterm', () => {
    const { api, term, docEvents } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript',
    });
    api.handleMouseDown(term, realMouseDown());
    assert.equal(api._isForcedGesture(), true, 'the gesture must be marked in flight');
    const up = realMouseUp();
    api.handleMouseUp(up);
    assert.equal(up.propagationStopped, true,
        'xterm binds a STANDING mouseup report listener with no force-selection check; '
        + 'letting it fire sends a report, and a report is user input, and user input '
        + 'clears the selection the drag just made');
    assert.equal(docEvents.length, 1,
        'SelectionService listens on document and still needs the mouseup, or its '
        + 'document mousemove handler is never removed and the selection keeps '
        + 'following the pointer after release');
    assert.equal(docEvents[0].type, 'mouseup');
    assert.equal(docEvents[0].clientX, 42);
    assert.equal(docEvents[0].clientY, 77);
    assert.equal(api._isForcedGesture(), false, 'the gesture must be marked finished');
});

test('DEFECT 2: a mouseup with no forced gesture in flight is left completely alone', () => {
    const { api, docEvents } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'live',
    });
    const up = realMouseUp();
    api.handleMouseUp(up);
    assert.equal(up.propagationStopped, false,
        'an ordinary click on a live app must reach that app');
    assert.equal(docEvents.length, 0, 'and must not be duplicated onto document');
});

test('DEFECT 3: motion is withheld while a selection exists in a scrolled transcript', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript', hasSelection: true,
    });
    const mv = realMouseMove();
    api.handleMouseMove(term, mv);
    assert.equal(mv.propagationStopped, true,
        'claude enables ?1003h, so an unsuppressed move is a report, and the report '
        + 'clears the finished selection on the very next twitch of the mouse');
});

test('DEFECT 3: motion is NOT withheld when there is no selection to protect', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript', hasSelection: false,
    });
    const mv = realMouseMove();
    api.handleMouseMove(term, mv);
    assert.equal(mv.propagationStopped, false,
        'with nothing to protect this must do nothing, so claude\'s own hover UI in the '
        + 'transcript behaves exactly as it did before');
});

test('DEFECT 3: motion is NOT withheld at the live bottom, even with a selection', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'live', hasSelection: true,
    });
    const mv = realMouseMove();
    api.handleMouseMove(term, mv);
    assert.equal(mv.propagationStopped, false,
        'a live view is exactly the case where the app\'s own mouse handling is correct '
        + 'and must not be interfered with - vim and htop live here');
});

test('DEFECT 3: motion is NOT withheld mid-drag, or the drag could not extend', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript', hasSelection: true,
    });
    api.handleMouseDown(term, realMouseDown());
    const mv = realMouseMove({ buttons: 1 });
    api.handleMouseMove(term, mv);
    assert.equal(mv.propagationStopped, false,
        'SelectionService extends the selection from its own document-level mousemove; '
        + 'cancelling propagation during the drag would starve it. xterm already '
        + 'declines to report a move while a button is held, so there is nothing to '
        + 'suppress here anyway');
});

test('DEFECT 3: motion is NOT withheld when mouse tracking is off', () => {
    const { api, term } = loadModuleReentrant({
        pinned: false, mouseActive: false, hasSelection: true,
    });
    const mv = realMouseMove();
    api.handleMouseMove(term, mv);
    assert.equal(mv.propagationStopped, false,
        'no tracking means no report means nothing that could clear the selection');
});

test('a term whose hasSelection() throws fails closed rather than swallowing motion', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript', hasSelection: true,
    });
    term.hasSelection = () => { throw new Error('renderer gone'); };
    const mv = realMouseMove();
    assert.doesNotThrow(() => api.handleMouseMove(term, mv));
    assert.equal(mv.propagationStopped, false);
});

test('init wires all three capture-phase listeners on the container', () => {
    const { api, term } = loadModuleReentrant({
        pinned: true, mouseActive: true, altScreenState: 'transcript',
    });
    api._reset();
    const wired = [];
    const container = {
        id: 'terminal',
        addEventListener(type, fn, opts) { wired.push({ type, capture: !!(opts && opts.capture) }); },
    };
    api.init(container, () => term);
    const types = wired.map((w) => w.type).sort();
    assert.deepEqual(types, ['mousedown', 'mousemove', 'mouseup'],
        'all three stages of the gesture must be handled - the down alone was the '
        + 'incomplete fix that shipped twice');
    assert.ok(wired.every((w) => w.capture),
        'every one must be capture-phase: the whole point is to run before xterm\'s '
        + 'own listeners on the descendant .xterm element');
});

test('every terminal gets its own instance: a second one wires too, and uninstall removes its listeners (u008-03)', () => {
    const { api } = loadModuleReentrant({ pinned: true, mouseActive: true, altScreenState: 'transcript' });
    assert.equal(typeof api.create, 'function', 'the module exposes the per-terminal factory');
    const mkContainer = () => {
        const c = { added: [], removed: [] };
        c.addEventListener = (type) => c.added.push(type);
        c.removeEventListener = (type) => c.removed.push(type);
        return c;
    };
    const a = api.create();
    const b = api.create();
    const ca = mkContainer();
    const cb = mkContainer();
    const offA = a.init(ca, () => null);
    b.init(cb, () => null);
    assert.equal(ca.added.length, 3, 'the first terminal wires');
    assert.equal(cb.added.length, 3, 'the second terminal wires too, it is not a no-op behind a shared flag');
    offA();
    assert.deepEqual(ca.removed.sort(), ['mousedown', 'mousemove', 'mouseup']);
    assert.equal(cb.removed.length, 0, 'tearing one down leaves the other alone');
    assert.equal(a._isForcedGesture(), false);
});

test('terminal.js resolves the select-while-scrolled module through _m, so a cell can carry its own (u008-03)', () => {
    const term = fs.readFileSync(new URL('../client/js/terminal.js', import.meta.url), 'utf8');
    assert.match(term, /this\._m\('TerminalSelectScrolled'\)/);
    assert.doesNotMatch(term, /window\.TerminalSelectScrolled\.init/);
});

console.log(`\n${passes} passed, ${failures} failed`);
process.exit(failures === 0 ? 0 : 1);

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
