
import assert from 'node:assert/strict';
import {
    ROOT, test, results, repoFile, loadModules, fakeStorage, Doc, plain, names,
} from './lib-sidebar-sessions.mjs';

const ARRANGEMENT_KEY = 'carnivore.session.sidebar.arrangement';
const DENSITY_KEY = 'carnivore.session.sidebar.density';

function row(over = {}) {
    return Object.assign({
        name: 'cloude_a',
        created_by_cloude: true,
        created_at_epoch: 1000,
        is_active: true,
        is_this_tab: false,
        is_pinned: false,
        status: 'working',
        unread: false,
        session_id: null,
        agent_family: null,
        agent_family_source: 'unknown',
        pinned_theme: null,
    }, over);
}

function loadArrangement(seed, throws = false) {
    const storage = fakeStorage(seed === null ? {} : { [ARRANGEMENT_KEY]: seed }, throws);
    const { window } = loadModules(['session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js'], { storage });
    delete window.BrowserStorageMigrate;
    return { A: window.SessionSidebarArrangement, storage };
}

// =====================================================================
// =====================================================================

await test('ITEM 46: a pinned session sorts above every unpinned one', () => {
    const { A } = loadArrangement(null);
    A.save(['b'], ['a', 'b', 'c']);
    const out = A.arrange([row({ name: 'a' }), row({ name: 'b' }), row({ name: 'c' })]);
    assert.deepEqual(names(out.rows), ['b', 'a', 'c']);
    assert.equal(out.rows[0].is_pinned, true, 'the row must carry the pin so the markup can draw it');
});

await test('ITEM 46: the pin is persisted under the arrangement key, versioned', () => {
    const { A, storage } = loadArrangement(null);
    A.togglePin('b', ['a', 'b', 'c']);
    const raw = storage.map.get(ARRANGEMENT_KEY);
    assert.ok(raw, `nothing was written to ${ARRANGEMENT_KEY}`);
    const parsed = JSON.parse(raw);
    assert.equal(parsed.v, A.VERSION);
    assert.deepEqual(plain(parsed.pinned), ['b']);
    assert.deepEqual(plain(parsed.order), ['a', 'b', 'c'],
        'the write records the list as the user is looking at it');
});

await test('ITEM 46: pinning is a TOGGLE - a second press really unpins', () => {
    const { A, storage } = loadArrangement(null);
    assert.equal(A.togglePin('b', ['a', 'b']), true, 'first press pins');
    assert.equal(A.togglePin('b', ['b', 'a']), false, 'second press must UNPIN, not re-pin');
    assert.deepEqual(plain(JSON.parse(storage.map.get(ARRANGEMENT_KEY)).pinned), []);
    assert.equal(A.isPinned('b'), false);
    assert.deepEqual(
        names(A.arrange([row({ name: 'a' }), row({ name: 'b' })]).rows), ['b', 'a'],
        'an unpinned row keeps its place in the order, it does not jump to the bottom');
});

await test('ITEM 46: a reload re-reads the pin from storage, it is not in-memory only', () => {
    const { A, storage } = loadArrangement(null);
    A.togglePin('b', ['a', 'b', 'c']);
    const { window } = loadModules(['session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js'], { storage });
    const fresh = window.SessionSidebarArrangement;
    fresh.load();
    assert.equal(fresh.isPinned('b'), true);
    assert.deepEqual(
        names(fresh.arrange([row({ name: 'a' }), row({ name: 'b' })]).rows),
        ['b', 'a'],
    );
});

// =====================================================================
// =====================================================================

await test('ITEM 46: a stored order beats the incoming poll order', () => {
    const { A } = loadArrangement(JSON.stringify({ v: 1, pinned: [], order: ['c', 'a', 'b'] }));
    A.load();
    const out = A.arrange([row({ name: 'a' }), row({ name: 'b' }), row({ name: 'c' })]);
    assert.deepEqual(names(out.rows), ['c', 'a', 'b']);
});

await test('ITEM 46: a session the arrangement has never seen lands at the END of its band', () => {
    const { A } = loadArrangement(JSON.stringify({ v: 1, pinned: ['c'], order: ['c', 'a'] }));
    A.load();
    const out = A.arrange([row({ name: 'a' }), row({ name: 'b' }), row({ name: 'c' })]);
    assert.deepEqual(names(out.rows), ['c', 'a', 'b'],
        'a brand new session must not jump above one the user placed');
});


await test('ITEM 65: a move ACROSS the band edge pins or unpins, and says it did', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);

    const up = plain(A.move('a', -1, ['p', 'a', 'b']));
    assert.deepEqual(up.order, ['a', 'p', 'b']);
    assert.equal(up.crossed, true, 'a crossing move must report that it crossed');
    assert.equal(up.pinned, true, 'moving up past the boundary pins the row');
    assert.equal(A.isPinned('a'), true, 'and the pin is actually applied, not just reported');
});

await test('ITEM 65: a move DOWN out of the pinned band unpins, the other direction', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    const down = plain(A.move('p', 1, ['p', 'a', 'b']));
    assert.deepEqual(down.order, ['a', 'p', 'b']);
    assert.equal(down.crossed, true);
    assert.equal(down.pinned, false, 'moving down past the boundary unpins the row');
    assert.equal(A.isPinned('p'), false);
});

await test('ITEM 65: a move WITHIN a band is not a crossing and changes no pin', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    const within = plain(A.move('b', -1, ['p', 'a', 'b']));
    assert.deepEqual(within.order, ['p', 'b', 'a']);
    assert.equal(within.crossed, false,
        'or every ordinary reorder would announce a pin change that did not happen');
    assert.equal(within.pinned, false);
});

await test('ITEM 65: the LIST edges are still hard refusals, unlike the band edge', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    assert.equal(A.move('p', -1, ['p', 'a', 'b']), null,
        'there is no row above the first one to cross past');
    assert.equal(A.move('b', 1, ['p', 'a', 'b']), null,
        'nor below the last one');
    assert.equal(A.isPinned('p'), true, 'a refused move must not have changed a pin either');
});


await test('ITEM 65: a drag INTO the pinned group pins the row', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    const res = plain(A.placeAt('b', true, 'p', ['p', 'a', 'b']));
    assert.deepEqual(res.order, ['b', 'p', 'a']);
    assert.equal(res.crossed, true);
    assert.equal(res.pinned, true);
    assert.equal(A.isPinned('b'), true);
});

await test('ITEM 65: a drag OUT of the pinned group unpins it, the other direction', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    const res = plain(A.placeAt('p', false, null, ['p', 'a', 'b']));
    assert.deepEqual(res.order, ['a', 'b', 'p']);
    assert.equal(res.crossed, true);
    assert.equal(res.pinned, false);
    assert.equal(A.isPinned('p'), false, 'dragging to the bottom of the other group unpins');
});

await test('ITEM 65: a drag into an EMPTY pinned group still pins', () => {
    const { A } = loadArrangement(null);
    A.save([], ['a', 'b']);
    const res = plain(A.placeAt('b', true, null, ['a', 'b']));
    assert.equal(res.pinned, true);
    assert.equal(res.crossed, true);
    assert.equal(A.isPinned('b'), true);
});

await test('ITEM 65: a drag WITHIN a band reorders and changes no pin', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    const res = plain(A.placeAt('b', false, 'a', ['p', 'a', 'b']));
    assert.deepEqual(res.order, ['p', 'b', 'a']);
    assert.equal(res.crossed, false);
    assert.equal(A.isPinned('b'), false);
});

await test('ITEM 65: a drop that changes NEITHER band nor sequence is not a move', () => {
    const { A } = loadArrangement(null);
    A.save(['p'], ['p', 'a', 'b']);
    assert.equal(A.placeAt('a', false, 'b', ['p', 'a', 'b']), null,
        'or a live drag writes storage and repaints on every pointer sample');
    assert.equal(A.placeAt('a', false, 'a', ['p', 'a', 'b']), null,
        'a row dropped on itself is not a move either');
});

await test('ITEM 46: a move is PERSISTED, not just applied in memory', () => {
    const { A, storage } = loadArrangement(null);
    A.save([], ['a', 'b', 'c']);
    A.move('c', -1, ['a', 'b', 'c']);
    assert.deepEqual(JSON.parse(storage.map.get(ARRANGEMENT_KEY)).order, ['a', 'c', 'b']);
});

// =====================================================================
// =====================================================================

await test('a remembered session that no longer exists KEEPS ITS SLOT and is reported', () => {
    const { A } = loadArrangement(JSON.stringify({
        v: 1, pinned: ['ghost'], order: ['ghost', 'a', 'b'],
    }));
    A.load();
    const out = A.arrange([row({ name: 'a' }), row({ name: 'b' })]);
    assert.deepEqual(names(out.rows), ['a', 'b'], 'it renders no row');
    assert.deepEqual(plain(out.missing), ['ghost'],
        'and it is NAMED, not silently dropped and not treated as an error');
});

await test('a gone session that is PINNED but not in the order is still reported', () => {
    const { A } = loadArrangement(JSON.stringify({
        v: 1, pinned: ['ghost'], order: ['a'],
    }));
    A.load();
    const out = A.arrange([row({ name: 'a' })]);
    assert.deepEqual(plain(out.missing), ['ghost']);
});

await test('a gone session that comes back returns to ITS OWN SLOT, not to the bottom', () => {
    const { A, storage } = loadArrangement(JSON.stringify({
        v: 1, pinned: [], order: ['a', 'ghost', 'b'],
    }));
    A.load();
    A.move('b', -1, ['a', 'b']);
    assert.deepEqual(JSON.parse(storage.map.get(ARRANGEMENT_KEY)).order, ['b', 'ghost', 'a'],
        'the absent name held index 1 through a reorder of the rows around it');
    const back = A.arrange([row({ name: 'a' }), row({ name: 'b' }), row({ name: 'ghost' })]);
    assert.deepEqual(names(back.rows), ['b', 'ghost', 'a']);
    assert.deepEqual(plain(back.missing), []);
});

await test('an ABSENT arrangement is not a failure and announces nothing', () => {
    const { A } = loadArrangement(null);
    const st = A.load();
    assert.equal(st.status, 'default');
    assert.equal(st.reason, null);
});

await test('a CORRUPT arrangement falls back to the default AND says so', () => {
    for (const [bad, why] of [
        ['{not json', 'not valid JSON'],
        ['[]', 'not an arrangement object'],
        ['{"v":9,"pinned":[],"order":[]}', 'version'],
        ['{"v":1,"pinned":[3],"order":[]}', 'list of session names'],
        ['{"v":1,"pinned":[],"order":"nope"}', 'list of session names'],
    ]) {
        const { A } = loadArrangement(bad);
        const st = A.load();
        assert.equal(st.status, 'unreadable', `${bad} must be unreadable, not silently accepted`);
        assert.match(st.reason, new RegExp(why), `${bad} must say WHY`);
        assert.deepEqual(plain(st.pinned), []);
        assert.deepEqual(
            names(A.arrange([row({ name: 'b' }), row({ name: 'a' })]).rows),
            ['b', 'a'], 'the incoming default order is used unchanged',
        );
    }
});

await test('a CORRUPT arrangement is NOT overwritten behind the user back', () => {
    const { A, storage } = loadArrangement('{not json');
    A.load();
    A.arrange([row({ name: 'a' })]);
    assert.equal(storage.map.get(ARRANGEMENT_KEY), '{not json',
        'the bytes stay on disk, inspectable, until a deliberate change replaces them');
});

await test('storage that THROWS is unreadable, not a crash and not a default', () => {
    const { A } = loadArrangement(null, true);
    const st = A.load();
    assert.equal(st.status, 'unreadable');
    assert.match(st.reason, /storage unavailable/);
});

await test('a deliberate arrangement change CLEARS the unreadable verdict', () => {
    const { A } = loadArrangement('{not json');
    A.load();
    A.togglePin('a', ['a', 'b']);
    assert.equal(A.current().status, 'ok',
        'once the user has told us an order there is no longer a lost one to warn about');
});

// =====================================================================
// =====================================================================

await test('ITEM 47: the density preference persists under its own key', () => {
    const storage = fakeStorage();
    const doc = new Doc();
    const { window } = loadModules(['session-sidebar-density.js'], { storage, document: doc });
    window.SessionSidebar = { panel: doc.createElement('aside'), repaint() {} };
    const D = window.SessionSidebarDensity;
    D.init();
    assert.equal(D.currentMode(), 'compact',
        'the default is COMPACT since 2026-09-21, the bar being docked open now');
    D.setMode('detailed');
    assert.equal(storage.map.get(DENSITY_KEY), 'detailed');
    assert.equal(window.SessionSidebar.panel.getAttribute('data-density'), 'detailed',
        'the panel must really carry the attribute the stylesheet keys off');
});

await test('ITEM 47: a stored density that is not a mode falls back rather than being applied', () => {
    const storage = fakeStorage({ [DENSITY_KEY]: 'enormous' });
    const doc = new Doc();
    const { window } = loadModules(['session-sidebar-density.js'], { storage, document: doc });
    window.SessionSidebar = { panel: doc.createElement('aside'), repaint() {} };
    window.SessionSidebarDensity.init();
    assert.equal(window.SessionSidebarDensity.currentMode(), 'compact');
});

await test('DEFAULT COMPACT: absent is compact, a stored mode is honoured', () => {
    const mk = (seed) => {
        const doc = new Doc();
        const { window } = loadModules(['session-sidebar-density.js'],
            { storage: fakeStorage(seed), document: doc });
        window.SessionSidebar = { panel: doc.createElement('aside'), repaint() {} };
        window.SessionSidebarDensity.init();
        return window.SessionSidebarDensity;
    };
    assert.equal(mk({}).currentMode(), 'compact', 'nothing stored');
    assert.equal(mk({ [DENSITY_KEY]: '' }).currentMode(), 'compact', 'an empty string');
    assert.equal(mk({ [DENSITY_KEY]: 'cozy' }).currentMode(), 'cozy', 'an explicit cozy');
    assert.equal(mk({ [DENSITY_KEY]: 'detailed' }).currentMode(), 'detailed');
    assert.equal(mk({ [DENSITY_KEY]: 'compact' }).currentMode(), 'compact');
});

await test('every place that spells the default density spells the SAME one', () => {
    const D = repoFile('web', 'src', 'lib', 'drawer', 'density.ts');
    assert.match(D, /export const DEFAULT_MODE = 'compact';/);
    const paint = repoFile('web', 'src', 'lib', 'drawer', 'paint.ts');
    assert.ok(paint.includes('const density = currentMode();'),
        'the drawer paint must take the density store\'s mode');
    assert.ok(!/'cozy'/.test(paint), 'no cozy fallback left in the paint module');
    const sidebar = repoFile('web', 'src', 'lib', 'drawer', 'controller.ts');
    assert.ok(!/:\s*'cozy';/.test(sidebar), 'no cozy fallback left in the controller');
    const html = repoFile('client', 'index.html');
    assert.match(html, /id="session-sidebar-panel"[\s\S]{0,200}data-density="compact"/,
        'the shipped panel attribute must agree, or the first paint disagrees');
});

await test('ITEM 47: the stylesheet really declares three different row paddings', () => {
    const css = repoFile('client', 'css', 'session-sidebar-density.css');
    const pad = (mode) => {
        const m = css.match(new RegExp(
            `\\[data-density="${mode}"\\][^\\{]*\\.session-sidebar-row-main\\s*\\{([^\\}]*)\\}`));
        assert.ok(m, `no row-main rule for ${mode}`);
        const p = m[1].match(/padding:\s*([^;]+);/);
        assert.ok(p, `${mode} declares no padding`);
        return p[1].trim();
    };
    const [c, z, d] = ['compact', 'cozy', 'detailed'].map(pad);
    assert.notEqual(c, z, 'compact and cozy must not be the same box');
    assert.notEqual(z, d, 'cozy and detailed must not be the same box');
});

await test('no sidebar row paints an inline-start rail, in any stylesheet', () => {
    // the current session
    const rail = /inset\s+[1-9]\d*px\s+0\s+0/;
    for (const file of ['session-sidebar.css', 'session-sidebar-rows.css',
                        'session-sidebar-density.css',
                        'session-sidebar-groups.css', 'session-theme-tint.css']) {
        const live = repoFile('client', 'css', file).split('\n')
            .filter((l) => !l.trim().startsWith('*') && !l.trim().startsWith('/*'))
            .join('\n');
        assert.doesNotMatch(live, rail,
            `${file} declares an inline-start rail on a sidebar row`);
    }
});

await test('a sidebar row carries the home screen ONE border, four sides', () => {
    const css = repoFile('client', 'css', 'session-sidebar-rows.css');
    const m = css.match(/\.session-sidebar-row\s*\{([^}]*)\}/);
    assert.ok(m, 'no .session-sidebar-row rule');
    assert.match(m[1], /border:\s*1px solid var\(--oc-line-panel\)/,
        'a transparent border here would leave the dense list with no separation '
        + 'at all once the rails are gone');
    assert.ok(!/border-left/.test(m[1]),
        'a border-left override is the same left-side bar wearing a different property');
});

// =====================================================================
// =====================================================================

// =====================================================================
// =====================================================================

await test('ITEM 63: the sidebar row draws no family pill at all', () => {
    for (const rel of [
        ['web', 'src', 'lib', 'sidebar-shell', 'row-plan.ts'],
        ['web', 'src', 'lib', 'sidebar-shell', 'row-chips.ts'],
        ['web', 'src', 'lib', 'sidebar-shell', 'SessionRow.svelte'],
    ]) {
        const src = repoFile(...rel)
            .replace(/\/\*[\s\S]*?\*\//g, '')
            .replace(/<!--[\s\S]*?-->/g, '')
            .replace(/\/\/.*/g, '');
        assert.ok(!/family-pill/.test(src), `${rel.join('/')} must not reference the pill class`);
    }
});

await test('ITEM 63: the unknown-family message carries no tilde of its own', () => {
    const catalog = repoFile('client', 'js', 'i18n', 'catalog.en.js');
    const unknown = catalog.match(/'session\.agent\.family\.unknown': '([^']*)'/);
    assert.ok(unknown, 'the unknown-family message must exist');
    assert.ok(!unknown[1].includes('~'), 'and it must not carry a tilde either');
});

// =====================================================================
// =====================================================================

await test('a fetch whose ATTACHABLE probe failed reports unavailable, not ok', async () => {
    const { window } = loadModules(['session-listing-state.js', 'session-sidebar-fetch.js']);
    const err = new Error('nope');
    err.status = 503;
    err.detail = { listing_reason: 'timeout', listing_detail: 'the probe timed out' };
    window.API = {
        async listAttachableSessions() { throw err; },
        async listSessions() { return []; },
    };
    const out = await window.SessionSidebarFetch.load(null);
    assert.equal(out.listing.ok, false);
    assert.equal(out.listing.reason, 'timeout');
    assert.deepEqual(plain(out.rows), []);
});

await test('a fetch whose LIVE list failed is still ok - that probe answers a different question', async () => {
    const { window } = loadModules(['session-listing-state.js', 'session-sidebar-fetch.js']);
    window.API = {
        async listAttachableSessions() {
            return [{ name: 'cloude_a', created_by_cloude: true, created_at_epoch: 1 }];
        },
        async listSessions() { throw new Error('no backend in this tab'); },
    };
    const out = await window.SessionSidebarFetch.load(null);
    assert.equal(out.listing.ok, true,
        'not knowing which rows have a live backend is not the same as not knowing what exists');
    assert.equal(out.rows.length, 1);
});

// =====================================================================
// =====================================================================

// =====================================================================
// =====================================================================

await test('a poll tick is DROPPED mid-drag rather than reordering under the finger', async () => {
    const src = repoFile('web', 'src', 'lib', 'drawer', 'controller.ts');
    assert.match(src, /sidebarShell\.isDragging\(\)\) return;/,
        'the fetch path must bail while a drag is in flight');
});

// =====================================================================
// =====================================================================

await test('ITEM 45: the home screen SHOWS the sidebar instead of hiding it', () => {
    const src = repoFile('client', 'js', 'app.js');
    const start = src.indexOf('showLaunchpad() {');
    const body = src.slice(start, src.indexOf('showTerminal(', start));
    assert.ok(body.includes('window.SessionSidebar.show()'),
        'the home screen must mount the bar');
    assert.ok(!/SessionSidebar\.hide\(\)/.test(body),
        'and must not hide it, which is what dropped a pinned bar on every trip home');
});

await test('ITEM 45: leaving a screen does NOT clobber the persisted open state', () => {
    const src = repoFile('web', 'src', 'lib', 'drawer', 'controller.ts');
    const hide = src.slice(src.indexOf('    hide(): void {'), src.indexOf('setActiveSession('));
    assert.match(hide, /close\(\{ persist: false \}\)/,
        'hide() used to persist "closed", so a pinned-open bar came back closed');
    assert.match(src, /const persist = !opts \|\| opts\.persist !== false;/,
        'close() must default to persisting so a real user close still sticks');
});

await test('ITEM 45: the docked offset really reaches the home screen ID selector', () => {
    // the home screen
    const css = repoFile('client', 'css', 'session-sidebar.css');
    assert.match(css, /body\.session-sidebar-pinned \{\s*--dock-offset: var\(--sidebar-dock-w\);\s*\}/,
        'docked, the drawer publishes exactly the dock width');
    const homeBar = repoFile('client', 'css', 'home-bar.css');
    assert.match(homeBar, /#launchpad-screen \{[^}]*padding: 0 0 0 var\(--dock-offset, 0\);/,
        'the unlayered home rule pays the dock offset and no gutter of its own');
});

// =====================================================================
// =====================================================================

// =====================================================================
// =====================================================================

const SIDEBAR_FILES = [
    ['client', 'js', 'session-entry-toasts.js'],
    ['client', 'css', 'session-sidebar-density.css'], ['client', 'css', 'session-sidebar.css'],
    ['client', 'css', 'session-sidebar-rows.css'],
    ...['arrangement', 'store', 'density', 'fetch', 'listing-state', 'paint', 'controller', 'pin', 'bar', 'boot']
        .map((m) => ['web', 'src', 'lib', 'drawer', `${m}.ts`]),
];

await test('every new sidebar file stays under the 1000-line budget', () => {
    for (const parts of SIDEBAR_FILES) {
        const lines = repoFile(...parts).split('\n').length;
        assert.ok(lines <= 1000, `${parts.join('/')} is ${lines} lines, over the 1000 budget`);
    }
});

await test('nothing added here uses an em-dash, an en-dash, or an emoji', () => {
    for (const parts of SIDEBAR_FILES) {
        const text = repoFile(...parts);
        const em = (text.match(new RegExp(String.fromCharCode(8212), 'g')) || []).length;
        const en = (text.match(new RegExp(String.fromCharCode(8211), 'g')) || []).length;
        assert.equal(em, 0, `${parts.join('/')} has ${em} em-dashes`);
        assert.equal(en, 0, `${parts.join('/')} has ${en} en-dashes`);
    }
});

await test('every new module is actually SERVED - a file nobody loads is dead code', () => {
    const html = repoFile('client', 'index.html');
    assert.ok(html.includes('/static/dist/app.js'), 'the bundle is not in index.html');
    assert.ok(!html.includes('session-sidebar-reorder.js'), 'the retired reorder facade is still served');
    assert.ok(html.includes('/static/css/session-sidebar-density.css'));
    assert.ok(html.includes('/static/css/session-sidebar-rows.css'),
        'the row stylesheet is not linked');
    const cidx = (s) => html.indexOf(`/static/css/${s}`);
    assert.ok(cidx('session-sidebar.css') < cidx('session-sidebar-rows.css'));
    assert.ok(cidx('session-sidebar-rows.css') < cidx('session-sidebar-density.css'));
    assert.ok(cidx('session-sidebar-rows.css') < cidx('session-sidebar-row-controls.css'));
    assert.match(html, /<script type="module" src="\/static\/dist\/app\.js/,
        'the bundle must be a module script, which is what defers it past the classic modules it reads');
});

await test('the density control\'s row and the live region are in the shipped markup', () => {
    const html = repoFile('client', 'index.html');
    assert.ok(html.includes('id="session-sidebar-header"'));
    assert.ok(repoFile('web', 'src', 'lib', 'drawer', 'DrawerHeader.svelte').includes('id="session-sidebar-topbar-controls"'));
    assert.ok(!html.includes('id="session-sidebar-tabs"'), 'the classic tab strip is gone');
    assert.ok(!html.includes('id="session-sidebar-density"'), 'the heading no longer carries it');
    assert.ok(html.includes('id="session-sidebar-live"'));
    assert.match(html, /id="session-sidebar-list"[^>]*\srole="listbox"/,
        'the list needs listbox semantics for the roving tabindex to mean anything');
});

const { passes, failures } = results();
console.log(`${passes} passed, ${failures} failed`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
