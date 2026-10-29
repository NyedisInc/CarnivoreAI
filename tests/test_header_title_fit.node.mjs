
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';
import { createEnvironment } from './mini-dom.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

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

/**
 * Read a CSS file from the client.
 * @param {string} name  File name under client/css.
 * @returns {string} File contents.
 */
function css(name) {
    return fs.readFileSync(path.join(__dirname, '..', 'client', 'css', name), 'utf8');
}

function ruleBody(source, selector) {
    const lines = source.split('\n');
    for (let i = 0; i < lines.length; i++) {
        if (lines[i].trim() !== selector + ' {') continue;
        const out = [];
        for (let j = i + 1; j < lines.length && lines[j].trim() !== '}'; j++) {
            out.push(lines[j]);
        }
        return out.join('\n');
    }
    throw new Error(`selector not found: ${selector}`);
}

function loadModule() {
    const env = createEnvironment({});
    const sandbox = {
        window: env.window,
        document: env.document,
        console: { log() {}, warn() {}, error() {} },
    };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(
            path.join(__dirname, '..', 'client', 'js', 'header-title-fit.js'), 'utf8'),
        sandbox);
    return env.window.HeaderTitleFit;
}

const measure = (text) => text.length * 10;

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('h1 sets min-width: 0 so it can shrink below its own text', () => {
    const body = ruleBody(css('styles.css'), '.header h1');
    assert.match(body, /min-width:\s*0\s*;/,
        'h1 must declare min-width: 0');
    assert.match(body, /overflow:\s*hidden\s*;/,
        'h1 must clip, or the shrunk box still paints its overflow');
});

test('the title span truncates instead of overflowing', () => {
    const body = ruleBody(css('styles.css'), '#header-title-text');
    assert.match(body, /min-width:\s*0\s*;/);
    assert.match(body, /overflow:\s*hidden\s*;/);
    assert.match(body, /text-overflow:\s*ellipsis\s*;/);
    assert.match(body, /white-space:\s*nowrap\s*;/);
});

test('.controls never shrinks, so the buttons cannot be pushed off screen', () => {
    const body = ruleBody(css('styles.css'), '.controls');
    assert.match(body, /flex-shrink:\s*0\s*;/,
        '.controls must declare flex-shrink: 0');
});

test('the fixed-size header identity parts opt out of shrinking', () => {
    const styles = css('styles.css');
    assert.match(ruleBody(styles, '.header-icon'), /flex-shrink:\s*0\s*;/);
    assert.match(ruleBody(styles, '.version'), /flex-shrink:\s*0\s*;/);
    assert.match(ruleBody(styles, '.header-rename-pencil'), /flex-shrink:\s*0\s*;/);
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

test('text that already fits is returned untouched', () => {
    const fit = loadModule();
    assert.equal(fit._elideToWidth('short', 1000, measure), 'short');
    assert.equal(fit._elideToWidth('', 100, measure), '');
});

test('an over-wide string is elided to something that actually fits', () => {
    const fit = loadModule();
    const full = 'cloude_claude-config-sync-2';
    const out = fit._elideToWidth(full, 180, measure);
    assert.notEqual(out, full, 'must have been shortened');
    assert.ok(measure(out) <= 180, `result must fit: ${out} = ${measure(out)}px`);
    assert.ok(out.includes('…'), 'must mark the removed middle');
});

test('elision is in the MIDDLE, so the distinguishing tail survives', () => {
    const fit = loadModule();
    const a = fit._elideToWidth('cloude_claude-config-sync-1', 180, measure);
    const b = fit._elideToWidth('cloude_claude-config-sync-2', 180, measure);
    assert.notEqual(a, b, 'sibling session names must stay distinguishable');
    assert.ok(a.endsWith('1'), `tail lost: ${a}`);
    assert.ok(b.endsWith('2'), `tail lost: ${b}`);
    assert.ok(a.startsWith('c'), `head lost: ${a}`);
});

test('the tail is favoured over the head when the budget is tight', () => {
    const fit = loadModule();
    const out = fit._elideToWidth('aaaaaaaaaaaaaaaaaaaazzzzzz', 90, measure);
    const tail = out.slice(out.indexOf('…') + 1);
    const head = out.slice(0, out.indexOf('…'));
    assert.ok(tail.length >= head.length,
        `tail (${tail}) must not be shorter than head (${head})`);
});

test('a wider budget never yields fewer characters', () => {
    const fit = loadModule();
    const full = 'cloude_claude-config-sync-2';
    let previous = -1;
    for (let w = 40; w <= 400; w += 20) {
        const len = fit._elideToWidth(full, w, measure).length;
        assert.ok(len >= previous, `width ${w} regressed: ${len} < ${previous}`);
        previous = len;
    }
});

test('degenerate budgets do not throw or produce garbage', () => {
    const fit = loadModule();
    const full = 'cloude_claude-config-sync-2';
    assert.equal(fit._elideToWidth(full, 0, measure), full);
    assert.equal(fit._elideToWidth(full, -10, measure), full);
    assert.equal(typeof fit._elideToWidth(full, 1, measure), 'string');
});

test('very short names are never elided, since it would not save anything', () => {
    const fit = loadModule();
    assert.equal(fit._elideToWidth('abc', 1, measure), 'abc');
});

test('setTitle and refresh are safe when the title is not mounted', () => {
    const fit = loadModule();
    assert.doesNotThrow(() => fit.setTitle('anything'));
    assert.doesNotThrow(() => fit.refresh());
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

function loadModuleWithLayout() {
    const env = createEnvironment({});
    const doc = env.document;

    const header = doc.createElement('div');
    const h1 = doc.createElement('h1');
    const titleEl = doc.createElement('span');
    titleEl.setAttribute('id', 'header-title-text');
    titleEl.dataset = {};
    for (const el of [h1, titleEl]) {
        Object.defineProperty(el, 'parentElement', { get() { return this.parentNode; } });
    }
    header.appendChild(h1);
    h1.appendChild(titleEl);
    doc.body.appendChild(header);
    header.clientWidth = 400;

    const realCreateElement = doc.createElement.bind(doc);
    doc.createElement = (tag) => {
        const el = realCreateElement(tag);
        el.getBoundingClientRect = () => ({ width: (el.textContent || '').length * 6 });
        return el;
    };

    let geometryCalls = 0;
    const fakeCS = {
        font: '14px sans-serif', letterSpacing: 'normal',
        paddingLeft: '0px', paddingRight: '0px',
        marginLeft: '0px', marginRight: '0px',
        columnGap: '0px', gap: '0px', display: 'inline',
    };

    const resizeHandlers = [];
    const sandboxWindow = {
        document: doc,
        console: { log() {}, warn() {}, error() {} },
        getComputedStyle(el) {
            if (el === header || el === h1) geometryCalls++;
            return fakeCS;
        },
        addEventListener(type, fn) {
            if (type === 'resize') resizeHandlers.push(fn);
        },
    };
    sandboxWindow.window = sandboxWindow;

    const sandbox = { window: sandboxWindow, document: doc, console: sandboxWindow.console };
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(
        fs.readFileSync(
            path.join(__dirname, '..', 'client', 'js', 'header-title-fit.js'), 'utf8'),
        sandbox);

    return {
        fit: sandbox.window.HeaderTitleFit,
        header, h1, titleEl,
        geometryCalls: () => geometryCalls,
        fireResize() { for (const fn of resizeHandlers.slice()) fn(); },
    };
}

test('a second setTitle() reuses the cached available width - no re-measurement', () => {
    const s = loadModuleWithLayout();
    s.fit.setTitle('cloude_claude-config-sync-1');
    const afterFirst = s.geometryCalls();
    assert.ok(afterFirst > 0, 'the first fit must have measured the geometry at all');

    s.fit.setTitle('cloude_claude-config-sync-2');
    assert.equal(s.geometryCalls(), afterFirst,
        'a title-only change must not re-measure the header geometry');
});

test('a window resize invalidates the cache - the NEXT fit re-measures', () => {
    const s = loadModuleWithLayout();
    s.fit.setTitle('cloude_claude-config-sync-1');
    const afterFirst = s.geometryCalls();

    s.fireResize();
    assert.ok(s.geometryCalls() > afterFirst,
        'a resize must force the next fit to re-measure the geometry');
});

test('re-measuring after a resize still returns a title-appropriate fit', () => {
    const s = loadModuleWithLayout();
    s.fit.setTitle('cloude_claude-config-sync-1');
    const before = s.titleEl.textContent;
    s.fireResize();
    s.fit.refresh();
    assert.equal(s.titleEl.textContent, before);
});

test('index.html loads the module and app.js routes the title through it', () => {
    const html = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'index.html'), 'utf8');
    assert.ok(html.includes('/static/js/header-title-fit.js'),
        'index.html must load header-title-fit.js');
    const app = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'app.js'), 'utf8');
    assert.ok(app.includes('HeaderTitleFit.setTitle'),
        'setHeaderIdentity must hand the full name to the fitter');
    const rename = fs.readFileSync(
        path.join(__dirname, '..', 'client', 'js', 'terminal-header-rename.js'), 'utf8');
    assert.ok(rename.includes('HeaderTitleFit.setTitle'),
        'a rename must repaint through the fitter, not raw textContent');
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
