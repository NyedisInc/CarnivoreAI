
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT_JS = path.join(__dirname, '..', 'client', 'js');
const CLIENT_CSS = path.join(__dirname, '..', 'client', 'css');
const opacitySrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal-background-opacity.js'), 'utf8');
const terminalSrc = fs.readFileSync(path.join(CLIENT_JS, 'terminal.js'), 'utf8');
const opacityCss = fs.readFileSync(path.join(CLIENT_CSS, 'terminal-opacity.css'), 'utf8');

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

function makeSandbox(withTerminalJs) {
    const dataset = {};
    const fakeDocument = {
        documentElement: { dataset },
        getElementById() { return null; },
        querySelectorAll() { return []; },
        createElement() {
            return { addEventListener() {}, classList: { add() {}, remove() {} }, style: {}, dataset: {} };
        },
    };
    const fakeWindow = { location: { origin: 'http://test.invalid' } };
    fakeWindow.window = fakeWindow;
    const context = {
        window: fakeWindow,
        document: fakeDocument,
        console,
        setTimeout,
        clearTimeout,
        MutationObserver: class { observe() {} disconnect() {} },
    };
    vm.createContext(context);
    vm.runInContext(opacitySrc, context, { filename: 'terminal-background-opacity.js' });
    if (withTerminalJs) {
        // terminal.js's boot line is one call into the terminal client
        // factory, so the factory has to be in this sandbox first, exactly
        // as index.html loads it first.
        vm.runInContext(fs.readFileSync(
            path.join(CLIENT_JS, 'terminal-client-factory.js'), 'utf8'),
            context, { filename: 'terminal-client-factory.js' });
        vm.runInContext(terminalSrc, context, { filename: 'terminal.js' });
    }
    return {
        api: context.window.TerminalBackgroundOpacity,
        setStatus(status) {
            if (status === undefined) delete dataset.themeEffects;
            else dataset.themeEffects = status;
        },
    };
}

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
function assertChannels(actual, expected) {
    assert.ok(actual, 'expected a parsed colour, got null');
    assert.equal(actual.r, expected.r, 'r channel');
    assert.equal(actual.g, expected.g, 'g channel');
    assert.equal(actual.b, expected.b, 'b channel');
}

test('parses #rrggbb', () => {
    const { api } = makeSandbox(false);
    assertChannels(api.parseCssColorChannels('#1e1e1e'), { r: 30, g: 30, b: 30 });
});

test('parses #rgb shorthand', () => {
    const { api } = makeSandbox(false);
    assertChannels(api.parseCssColorChannels('#3f0'), { r: 51, g: 255, b: 0 });
});

test('parses rgb() and rgba()', () => {
    const { api } = makeSandbox(false);
    assertChannels(api.parseCssColorChannels('rgb(10, 20, 30)'), { r: 10, g: 20, b: 30 });
    assertChannels(api.parseCssColorChannels('rgba(10, 20, 30, 0.5)'), { r: 10, g: 20, b: 30 });
});

test('is case-insensitive on hex digits', () => {
    const { api } = makeSandbox(false);
    assertChannels(api.parseCssColorChannels('#AaBbCc'), { r: 170, g: 187, b: 204 });
});

test('returns null for an unparseable colour (named colour, css var, junk)', () => {
    const { api } = makeSandbox(false);
    assert.equal(api.parseCssColorChannels('transparent'), null);
    assert.equal(api.parseCssColorChannels('var(--color-bg)'), null);
    assert.equal(api.parseCssColorChannels('not-a-colour'), null);
    assert.equal(api.parseCssColorChannels(''), null);
    assert.equal(api.parseCssColorChannels(undefined), null);
    assert.equal(api.parseCssColorChannels(null), null);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('running/paused/static all read as visible', () => {
    const { api, setStatus } = makeSandbox(false);
    for (const status of ['running', 'paused', 'static']) {
        setStatus(status);
        assert.equal(api.isThemeEffectVisible(), true, `status=${status}`);
    }
});

test('unavailable/skipped/inactive all read as NOT visible', () => {
    const { api, setStatus } = makeSandbox(false);
    for (const status of ['unavailable', 'skipped', 'inactive']) {
        setStatus(status);
        assert.equal(api.isThemeEffectVisible(), false, `status=${status}`);
    }
});

test('the attribute never having been set reads as NOT visible', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus(undefined);
    assert.equal(api.isThemeEffectVisible(), false);
});

test('a missing/broken document access degrades to NOT visible, never throws', () => {
    const context = {
        window: {},
        console,
    };
    context.window.window = context.window;
    vm.createContext(context);
    vm.runInContext(opacitySrc, context, { filename: 'terminal-background-opacity.js' });
    assert.doesNotThrow(() => context.window.TerminalBackgroundOpacity.isThemeEffectVisible());
    assert.equal(context.window.TerminalBackgroundOpacity.isThemeEffectVisible(), false);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('effect not visible: background left fully opaque, unchanged', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('unavailable');
    const raw = { background: '#000000', foreground: '#00ff41' };
    const out = api.withTerminalBackgroundOpacity(raw);
    assert.equal(out.background, '#000000');
    assert.equal(out.foreground, '#00ff41');
});

test('effect visible: background becomes rgba() at TERMINAL_BG_OPACITY', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('running');
    const raw = { background: '#000000', foreground: '#00ff41' };
    const out = api.withTerminalBackgroundOpacity(raw);
    assert.equal(out.background, 'rgba(0, 0, 0, 0.9)');
});

test('foreground and every ANSI colour are never touched', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('running');
    const raw = {
        background: '#0A0A0B', foreground: '#fafafa', cursor: '#fafafa',
        red: '#cd3131', green: '#0dbc79',
    };
    const out = api.withTerminalBackgroundOpacity(raw);
    assert.equal(out.foreground, raw.foreground);
    assert.equal(out.cursor, raw.cursor);
    assert.equal(out.red, raw.red);
    assert.equal(out.green, raw.green);
});

test('an unparseable background is left alone rather than guessed at', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('running');
    const raw = { background: 'var(--color-bg)', foreground: '#fff' };
    const out = api.withTerminalBackgroundOpacity(raw);
    assert.equal(out.background, 'var(--color-bg)');
});

test('null/undefined theme passes through without throwing', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('running');
    assert.equal(api.withTerminalBackgroundOpacity(null), null);
    assert.equal(api.withTerminalBackgroundOpacity(undefined), undefined);
});

test('TERMINAL_BG_OPACITY is 0.90 - the value the task specified', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('running');
    const out = api.withTerminalBackgroundOpacity({ background: '#ffffff' });
    assert.equal(out.background, 'rgba(255, 255, 255, 0.9)');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('a light background (carnivore-light\'s own #f1f2f3) gets the 4.5 floor', () => {
    const { api } = makeSandbox(false);
    assert.equal(api.minimumContrastRatioForXtermTheme({ background: '#f1f2f3' }), 4.5);
});

test('a dark background (claude\'s own #1e1e1e) stays at 1, unchanged', () => {
    const { api } = makeSandbox(false);
    assert.equal(api.minimumContrastRatioForXtermTheme({ background: '#1e1e1e' }), 1);
});

test('NEGATIVE CONTROL: a light background must NOT read as 1 (proves the assertion above can fail)', () => {
    const { api } = makeSandbox(false);
    assert.notEqual(api.minimumContrastRatioForXtermTheme({ background: '#f1f2f3' }), 1);
});

test('white and black are the unambiguous extremes', () => {
    const { api } = makeSandbox(false);
    assert.equal(api.minimumContrastRatioForXtermTheme({ background: '#ffffff' }), 4.5);
    assert.equal(api.minimumContrastRatioForXtermTheme({ background: '#000000' }), 1);
});

test('an unparseable background, no theme, or no background field defaults to 1, never guesses', () => {
    const { api } = makeSandbox(false);
    assert.equal(api.minimumContrastRatioForXtermTheme({ background: 'not-a-colour' }), 1);
    assert.equal(api.minimumContrastRatioForXtermTheme({}), 1);
    assert.equal(api.minimumContrastRatioForXtermTheme(null), 1);
    assert.equal(api.minimumContrastRatioForXtermTheme(undefined), 1);
});

test('attach(term).apply() sets minimumContrastRatio alongside theme, and resets it on a light-to-dark swap', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('unavailable');
    const fakeTerm = { options: {} };
    const controller = api.attach(fakeTerm);
    controller.apply({ background: '#f1f2f3' }); // carnivore-light
    assert.equal(fakeTerm.options.minimumContrastRatio, 4.5);
    controller.apply({ background: '#1e1e1e' });
    assert.equal(fakeTerm.options.minimumContrastRatio, 1, 'switching to a dark theme must reset the ratio to 1');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('attach(term).apply(theme) actually writes term.options.theme', () => {
    const { api, setStatus } = makeSandbox(false);
    setStatus('running');
    const fakeTerm = { options: { theme: null } };
    const controller = api.attach(fakeTerm);
    controller.apply({ background: '#000000', foreground: '#00ff41' });
    assert.equal(fakeTerm.options.theme.background, 'rgba(0, 0, 0, 0.9)');
    assert.equal(fakeTerm.options.theme.foreground, '#00ff41');
});

test('attach(term)\'s MutationObserver re-applies the last raw theme via apply(lastRaw)', () => {
    const dataset = {};
    let observerCallback = null;
    const fakeDocument = {
        documentElement: { dataset },
        getElementById() { return null; },
        querySelectorAll() { return []; },
        createElement() { return { addEventListener() {}, classList: { add() {}, remove() {} }, style: {}, dataset: {} }; },
    };
    const fakeWindow = {};
    fakeWindow.window = fakeWindow;
    const context = {
        window: fakeWindow,
        document: fakeDocument,
        console,
        MutationObserver: class {
            constructor(cb) { observerCallback = cb; }
            observe() {}
            disconnect() {}
        },
    };
    vm.createContext(context);
    vm.runInContext(opacitySrc, context, { filename: 'terminal-background-opacity.js' });
    const fakeTerm = { options: { theme: null } };
    const controller = context.window.TerminalBackgroundOpacity.attach(fakeTerm);
    dataset.themeEffects = 'unavailable';
    controller.apply({ background: '#000000' });
    assert.equal(fakeTerm.options.theme.background, '#000000');
    dataset.themeEffects = 'running';
    assert.ok(observerCallback, 'attach() must register a MutationObserver callback');
    observerCallback();
    assert.equal(fakeTerm.options.theme.background, 'rgba(0, 0, 0, 0.9)');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('terminal.js delegates to window.TerminalBackgroundOpacity rather than reimplementing it', () => {
    const { api } = makeSandbox(true);
    assert.ok(api, 'terminal-background-opacity.js must still export its API');
    assert.doesNotMatch(
        terminalSrc, /^function parseCssColorChannels/m,
        'parseCssColorChannels must live in terminal-background-opacity.js, not terminal.js'
    );
});

test('allowTransparency is true (required for rgba background to render)', () => {
    const factorySrc = fs.readFileSync(
        path.join(CLIENT_JS, 'terminal-client-factory.js'), 'utf8');
    assert.match(factorySrc, /allowTransparency:\s*true/);
    assert.ok(!/allowTransparency:/.test(terminalSrc),
        'terminal.js sets its own allowTransparency again, so there are two');
    assert.match(terminalSrc, /window\.TerminalBackgroundOpacity\.attach\(this\.term\)/);
    assert.match(terminalSrc, /this\._xtermOpacity\.apply\(initialXtermTheme\)/);
});

test('the xtermThemeChange listener re-derives opacity on every theme swap', () => {
    assert.match(terminalSrc, /this\._xtermOpacity\.apply\(newXtermTheme\)/);
});

test('a MutationObserver watches data-theme-effects and reapplies opacity', () => {
    assert.match(opacitySrc, /attributeFilter:\s*\['data-theme-effects'\]/);
    assert.match(opacitySrc, /apply\(lastRaw\)/);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------
test('the CSS override is gated on the same three statuses as the JS', () => {
    for (const status of ['running', 'paused', 'static']) {
        assert.match(
            opacityCss,
            new RegExp(`html\\[data-theme-effects="${status}"\\]\\s*#terminal`),
            `missing selector for status=${status}`
        );
    }
});

test('the CSS override sets #terminal to transparent, not some other value', () => {
    const idx = opacityCss.indexOf('#terminal {\n    background: transparent;');
    assert.ok(idx !== -1, 'expected "background: transparent;" rule body not found');
});

test('the CSS does not gate on unavailable/skipped/inactive (would defeat the fallback)', () => {
    for (const status of ['unavailable', 'skipped', 'inactive']) {
        assert.doesNotMatch(opacityCss, new RegExp(`data-theme-effects="${status}"`));
    }
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
