
import assert from 'node:assert/strict';
import {
    test, results, repoFile, Doc, plain, fakeStorage, loadModules,
} from './lib-sidebar-sessions.mjs';

const KEY = 'carnivore.session.sidebar.arrangement';

function loadArrangement(env = {}) {
    const storage = fakeStorage({
        [KEY]: JSON.stringify(Object.assign({ v: 1, pinned: [], order: [] }, env)),
    });
    const { window } = loadModules(
        ['session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js'], { storage },
    );
    window.SessionSidebarArrangement.load();
    return {
        window, A: window.SessionSidebarArrangement, S: window.SessionSidebarStore, storage,
    };
}

function stored(storage) { return JSON.parse(storage.map.get(KEY)); }

function rowsOf(names) { return names.map((name) => ({ name })); }

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

function declsFor(css, selector) {
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
    while ((m = re.exec(clean))) {
        const sels = m[1].split(',').map((s) => s.trim());
        if (sels.includes(selector)) out.push(m[2]);
    }
    return out;
}

function cursorOf(css, selector) {
    let value = null;
    for (const body of declsFor(css, selector)) {
        const m = body.match(/cursor:\s*([a-z-]+)/);
        if (m) value = m[1];
    }
    return value;
}

const CSS = ['session-sidebar-rows.css', 'session-sidebar-density.css',
    'session-sidebar-row-controls.css', 'session-sidebar.css']
    .map((f) => repoFile('client', 'css', f)).join('\n');

await test('CURSOR: the row body is the normal arrow, not a hand', () => {
    assert.equal(cursorOf(CSS, '.session-sidebar-row'), 'default');
    assert.equal(cursorOf(CSS, '.session-sidebar-row-main'), 'default');
});

await test('CURSOR: the hand shows over the status dot only', () => {
    assert.equal(cursorOf(CSS, '.session-sidebar-row .status-dot'), 'pointer');
});

await test('CURSOR: buttons in the row keep their hand, a drag keeps grabbing', () => {
    assert.equal(cursorOf(CSS, '.session-sidebar-row-main button'), 'pointer');
    assert.equal(cursorOf(CSS, '.session-sidebar-list--dragging .session-sidebar-row-main'), 'grabbing');
    assert.equal(cursorOf(CSS, '.session-sidebar-list--dragging .session-sidebar-row .status-dot'), 'grabbing',
        'the dot must not flip back to a hand mid-drag');
});

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

await test('a reorder inside a PROJECT band persists that band alone', () => {
    const { A, storage } = loadArrangement({ pinned: ['a'], order: ['a', 'b', 'c'] });
    const next = A.placeInBand('p:1', 'c', 'a', ['a', 'b', 'c']);
    assert.deepEqual(plain(next), ['c', 'a', 'b']);
    const env = stored(storage);
    assert.deepEqual(env.bands['p:1'], ['c', 'a', 'b']);
    assert.deepEqual(env.order, ['a', 'b', 'c'], 'the shared order pinned draws from must not move');
    assert.deepEqual(env.pinned, ['a'], 'no pin may change');
});

await test('a reorder inside a GROUP band persists and survives a reload', () => {
    const { A, storage } = loadArrangement({ order: ['a', 'b', 'c'] });
    A.placeInBand('g:x', 'a', null, ['a', 'b', 'c']);
    const again = loadModules(['session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js'], { storage });
    again.window.SessionSidebarArrangement.load();
    const drawn = again.window.SessionSidebarArrangement.orderBand('g:x', rowsOf(['a', 'b', 'c']));
    assert.deepEqual(drawn.map((r) => r.name), ['b', 'c', 'a']);
});

await test('a row in two bands reorders INDEPENDENTLY in each', () => {
    const { A } = loadArrangement({ order: ['a', 'b', 'c'] });
    A.placeInBand('p:1', 'a', null, ['a', 'b', 'c']);
    A.placeInBand('g:x', 'c', 'a', ['a', 'b', 'c']);
    const rows = rowsOf(['a', 'b', 'c']);
    assert.deepEqual(A.orderBand('p:1', rows).map((r) => r.name), ['b', 'c', 'a']);
    assert.deepEqual(A.orderBand('g:x', rows).map((r) => r.name), ['c', 'a', 'b']);
    assert.deepEqual(A.orderBand('pinned', rows).map((r) => r.name), ['a', 'b', 'c'],
        'pinned keeps the shared order');
});

await test('a NEW session a band never arranged lands at the END of that band', () => {
    const { A } = loadArrangement({ order: ['a', 'b'], bands: { 'p:1': ['b', 'a'] } });
    const drawn = A.orderBand('p:1', rowsOf(['new', 'a', 'b']));
    assert.deepEqual(drawn.map((r) => r.name), ['b', 'a', 'new']);
});

await test('a stopped session keeps its slot in a band order', () => {
    const { A, storage } = loadArrangement({ bands: { rogue: ['a', 'gone', 'b'] } });
    A.placeInBand('rogue', 'b', 'a', ['a', 'b']);
    assert.deepEqual(stored(storage).bands.rogue, ['b', 'gone', 'a']);
});

await test('a malformed band map is dropped, never the pins or the order', () => {
    const { A } = loadArrangement({ pinned: ['a'], order: ['a'], bands: { pinned: ['x'], 'p:1': 7 } });
    assert.equal(A.current().status, 'ok');
    assert.deepEqual(plain(A.current().pinned), ['a']);
    assert.deepEqual(plain(A.current().bands), {});
});

await test('moveInBand refuses at the band edge rather than crossing', () => {
    const { A } = loadArrangement();
    assert.equal(A.moveInBand('p:1', 'a', -1, ['a', 'b']), null);
    assert.equal(A.moveInBand('p:1', 'b', 1, ['a', 'b']), null);
    assert.deepEqual(plain(A.moveInBand('p:1', 'a', 1, ['a', 'b', 'c'])), ['b', 'a', 'c']);
});


// ---------------------------------------------------------------------
// ---------------------------------------------------------------------


const { passes, failures } = results();
console.log(`\n${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
