
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CLIENT = path.join(__dirname, '..', 'client');

let passes = 0;
let failures = 0;

/**
 * Run one named check.
 * @param {string} name  What is being asserted.
 * @param {Function} fn  The body; throws to fail.
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
        console.error(err && err.stack ? err.stack : err);
    }
}

function clientFile(...parts) {
    return fs.readFileSync(path.join(CLIENT, ...parts), 'utf8');
}

function load(opts = {}) {
    const { withAddon = true, cssVars = {} } = opts;
    const calls = { constructed: [], findNext: [], findPrevious: [], clear: 0 };
    const warns = [];

    class FakeSearchAddon {
        constructor(options) {
            calls.constructed.push(options);
            this._results = null;
        }
        onDidChangeResults(cb) { this._results = cb; }
        findNext(q, o) { calls.findNext.push([q, o]); return true; }
        findPrevious(q, o) { calls.findPrevious.push([q, o]); return true; }
        clearDecorations() { calls.clear++; }
        emit(r) { if (this._results) this._results(r); }
    }

    const container = { __isContainer: true };
    const sandbox = {
        console: { log() {}, warn: (...a) => { warns.push(a.join(' ')); },
            error() {}, debug() {} },
        WeakMap, Object, Promise, RegExp, String,
        document: {
            querySelector: (sel) => (sel === '.terminal-container' ? container : null),
        },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    sandbox.getComputedStyle = (el) => ({
        getPropertyValue: (name) => (el === container ? (cssVars[name] || '') : ''),
    });
    if (withAddon) sandbox.SearchAddon = { SearchAddon: FakeSearchAddon };

    vm.createContext(sandbox);
    vm.runInContext(clientFile('js', 'terminal-search-engine.js'), sandbox,
        { filename: 'terminal-search-engine.js' });

    function makeTerm() {
        const t = { loaded: [] };
        t.loadAddon = (a) => { t.loaded.push(a); };
        return t;
    }

    return { engine: sandbox.TerminalSearchEngine, calls, warns, makeTerm };
}


test('attach loads the add-on exactly once, however often it is called', () => {
    const h = load();
    const term = h.makeTerm();
    const a = h.engine.attach(term);
    const b = h.engine.attach(term);
    const c = h.engine.attach(term);
    assert.equal(term.loaded.length, 1,
        'the panel attaches on every open; a second add-on doubles every count');
    assert.equal(h.calls.constructed.length, 1);
    assert.equal(a, b);
    assert.equal(b, c);
});

test('the highlight limit is passed to the add-on, and it is the one we report', () => {
    const h = load();
    h.engine.attach(h.makeTerm());
    assert.equal(Object.keys(h.calls.constructed[0]).length, 1);
    assert.equal(h.calls.constructed[0].highlightLimit, 1000);
    assert.equal(h.engine.HIGHLIGHT_LIMIT, 1000,
        'the panel paints `1000+` at this number; one constant, not two');
});

test('a DIFFERENT terminal gets its own add-on - the positive twin', () => {
    const h = load();
    const one = h.makeTerm();
    const two = h.makeTerm();
    h.engine.attach(one);
    h.engine.attach(two);
    assert.equal(one.loaded.length, 1);
    assert.equal(two.loaded.length, 1);
    assert.notEqual(one.loaded[0], two.loaded[0], 'a session swap is a new add-on');
});


test('find runs forward or backward and carries the decoration block', () => {
    const h = load();
    h.engine.attach(h.makeTerm());
    h.engine.find('hazard', { incremental: true }, 'next');
    h.engine.find('hazard', { incremental: true }, 'prev');
    assert.equal(h.calls.findNext.length, 1);
    assert.equal(h.calls.findPrevious.length, 1);
    const opts = h.calls.findNext[0][1];
    assert.equal(h.calls.findNext[0][0], 'hazard');
    assert.equal(opts.incremental, true);
    assert.equal(opts.regex, false);
    assert.equal(opts.caseSensitive, false);
    assert.ok(opts.decorations, 'without decorations nothing is highlighted at all');
});

test('next and prev force incremental OFF, or Enter would stand still', () => {
    const h = load();
    h.engine.attach(h.makeTerm());
    h.engine.find('hazard', { incremental: true }, 'next');
    h.engine.next();
    h.engine.prev();
    assert.equal(h.calls.findNext[1][1].incremental, false);
    assert.equal(h.calls.findPrevious[0][1].incremental, false);
    assert.equal(h.calls.findNext[1][0], 'hazard', 'and they reuse the live query');
});

test('an empty query clears instead of searching for nothing', () => {
    const h = load();
    h.engine.attach(h.makeTerm());
    h.engine.find('hazard', {}, 'next');
    const before = h.calls.findNext.length;
    h.engine.find('', {}, 'next');
    assert.equal(h.calls.findNext.length, before, 'no search is run');
    assert.equal(h.calls.clear, 1, 'and the old highlights go');
});


test('a resultCount of -1 arrives as null, never as a number', () => {
    const h = load();
    const term = h.makeTerm();
    const addon = h.engine.attach(term);
    const seen = [];
    h.engine.onResults((r) => { seen.push(r); });
    addon.emit({ resultIndex: -1, resultCount: -1 });
    assert.equal(seen.length, 1);
    assert.equal(seen[0].resultCount, null,
        '-1 means NOT COUNTED; as a number the panel would paint no matches');
    assert.equal(seen[0].resultIndex, null);
});

test('a real zero is still a real zero - the positive twin', () => {
    const h = load();
    const addon = h.engine.attach(h.makeTerm());
    const seen = [];
    h.engine.onResults((r) => { seen.push(r); });
    addon.emit({ resultIndex: -1, resultCount: 0 });
    assert.equal(seen[0].resultCount, 0,
        'a counted zero must survive, or `no matches` could never be shown');
});

test('a listener that throws does not stop the others', () => {
    const h = load();
    const addon = h.engine.attach(h.makeTerm());
    let reached = 0;
    h.engine.onResults(() => { throw new Error('boom'); });
    h.engine.onResults(() => { reached++; });
    addon.emit({ resultIndex: 0, resultCount: 3 });
    assert.equal(reached, 1);
});

test('unsubscribing stops the callbacks', () => {
    const h = load();
    const addon = h.engine.attach(h.makeTerm());
    let n = 0;
    const off = h.engine.onResults(() => { n++; });
    addon.emit({ resultIndex: 0, resultCount: 1 });
    off();
    addon.emit({ resultIndex: 1, resultCount: 2 });
    assert.equal(n, 1);
});


test('predicate is case-insensitive by default', () => {
    const h = load();
    const p = h.engine.predicate('Hazard');
    assert.equal(p('the hazard report'), true);
    assert.equal(p('THE HAZARD REPORT'), true);
    assert.equal(p('nothing here'), false);
});

test('predicate honours caseSensitive when asked', () => {
    const h = load();
    const p = h.engine.predicate('Hazard', { caseSensitive: true });
    assert.equal(p('a Hazard'), true);
    assert.equal(p('a hazard'), false);
});

test('predicate in regex mode compiles the query', () => {
    const h = load();
    const p = h.engine.predicate('haz.rd', { regex: true });
    assert.equal(p('a hazard'), true);
    assert.equal(p('a hazird'), true);
    assert.equal(p('a hzrd'), false);
    const ci = h.engine.predicate('^ERR', { regex: true });
    assert.equal(ci('err: nope'), true, 'still case-insensitive unless asked');
    assert.equal(h.engine.predicate('^ERR', { regex: true, caseSensitive: true })('err'),
        false);
});

test('an UNFINISHED regex matches nothing, not everything', () => {
    const h = load();
    const p = h.engine.predicate('(unclosed', { regex: true });
    assert.equal(p('anything at all'), false);
    assert.equal(p(''), false);
});

test('an EMPTY query matches everything, which is the rail at rest', () => {
    const h = load();
    const p = h.engine.predicate('');
    assert.equal(p('anything'), true);
    assert.equal(p(''), true);
    assert.equal(h.engine.predicate(null)('x'), true);
});

test('predicate survives null and undefined text', () => {
    const h = load();
    const p = h.engine.predicate('x');
    assert.equal(p(null), false);
    assert.equal(p(undefined), false);
});


test('themed hex colours are used, and non-hex values are refused', () => {
    const h = load({ cssVars: {
        '--terminal-search-match-bg': '  #123456 ',
        '--terminal-search-active-bg': 'rgba(215, 119, 87, 0.15)',
    } });
    h.engine.attach(h.makeTerm());
    h.engine.find('q', {}, 'next');
    const d = h.calls.findNext[0][1].decorations;
    assert.equal(d.matchBackground, '#123456', 'a hex token is honoured, trimmed');
    assert.equal(d.activeMatchBackground, '#d77757',
        'an rgba() token is refused and the built-in default stands');
    assert.equal(d.matchBorder, '#8a5a44', 'an absent token falls back too');
    for (const k of ['matchBackground', 'matchBorder', 'matchOverviewRuler',
        'activeMatchBackground', 'activeMatchBorder',
        'activeMatchColorOverviewRuler']) {
        assert.match(d[k], /^#[0-9a-fA-F]{3,8}$/, `${k} must be a hex colour`);
    }
});

test('the CSS declares every custom property the engine reads', () => {
    const css = clientFile('dist', 'app.css');
    const js = clientFile('js', 'terminal-search-engine.js');
    const read = [...js.matchAll(/'(--terminal-search-[\w-]+)'/g)].map((m) => m[1]);
    assert.equal(read.length, 6, 'six decoration colours are read');
    for (const prop of read) {
        assert.ok(css.includes(`${prop}:`), `${prop} is read but never declared`);
    }
});


test('a missing add-on is a warned no-op, not a throw', () => {
    const h = load({ withAddon: false });
    const term = h.makeTerm();
    assert.equal(h.engine.attach(term), null);
    assert.equal(term.loaded.length, 0);
    assert.equal(h.engine.find('hazard', {}, 'next'), false);
    assert.equal(h.engine.next(), false);
    assert.equal(h.engine.prev(), false);
    h.engine.clear();
    assert.equal(h.warns.length, 1,
        'said once, not once per keystroke');
    assert.match(h.warns[0], /xterm-addon-search/);
});

test('predicate still works with no add-on, because the rail depends on it', () => {
    const h = load({ withAddon: false });
    assert.equal(h.engine.predicate('haz')('hazard'), true);
});

test('clear still reports a zero count with no add-on', () => {
    const h = load({ withAddon: false });
    const seen = [];
    h.engine.onResults((r) => { seen.push(r); });
    h.engine.clear();
    assert.equal(seen.length, 1);
    assert.equal(seen[0].resultCount, 0);
});


test('the vendored add-on is present, pinned and served from our own origin', () => {
    const file = path.join(CLIENT, 'vendor', 'xterm', 'xterm-addon-search.js');
    assert.ok(fs.existsSync(file), 'the add-on must be vendored, never CDN-loaded');
    const src = fs.readFileSync(file, 'utf8');
    assert.ok(src.includes('SearchAddon'), 'its UMD global is SearchAddon');
    const version = clientFile('vendor', 'xterm', 'VERSION.md');
    assert.ok(version.includes('xterm-addon-search'), 'and it must be recorded');
    assert.ok(version.includes('0.13.0'), 'with its pinned version');
    assert.ok(version.includes(
        '6a6db33f16b764552377a2c5ba4327c6dab6beaf25484533afd7dbecd0b03793'),
    'and its measured sha256');
    const fetchSh = fs.readFileSync(
        path.join(__dirname, '..', 'scripts', 'xterm-vendor', 'fetch.sh'), 'utf8');
    assert.ok(fetchSh.includes('xterm-addon-search'),
        'the refresh script must be able to re-verify it');
});

test('the engine stays under the 500-line budget', () => {
    const lines = clientFile('js', 'terminal-search-engine.js').split('\n').length;
    assert.ok(lines <= 500, `terminal-search-engine.js is ${lines} lines`);
});

console.log(`\n${passes} passed, ${failures} failed`);
if (failures > 0) { console.error('FAILURES'); process.exit(1); }
console.log('ALL PASS');
