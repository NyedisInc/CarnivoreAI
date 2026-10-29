import assert from 'node:assert/strict';
import { glyphSvg } from '../client/js/icons/glyphs.js';
import { iconSvg } from '../client/js/icons/icon-registry.js';
import { Doc, fakeStorage, loadModules, results, test } from './lib-sidebar-sessions.mjs';

const BASE = [
    'status-led.js', 'session-status-summary.js',
    'session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js',
    'session-sidebar-group-membership.js', 'session-sidebar-group-store.js',
    'session-sidebar-row-controls.js',
    'session-sidebar-search.js', 'session-sidebar-groups-search.js',
    'session-sidebar-project-header.js', 'session-sidebar-groups.js',
    'session-sidebar-fetch.js',
    'session-row-menu-icons.js', 'session-sidebar-group-actions.js',
    'session-sidebar-group-colour.js',
];

const UUID = 'g-1';
const KEY = `g:${UUID}`;

function stack(icon, withIconModule = true) {
    const { window } = loadModules(
        withIconModule ? [...BASE, 'session-sidebar-group-icon.js'] : BASE,
        { storage: fakeStorage({}), document: new Doc() },
    );
    window.CloudeGlyphs = { glyphSvg, iconSvg };
    window.SessionSidebarClicks = { paintSelection() {} };
    window.SessionSidebarGroupStore.apply({
        status: 'ok',
        groups: [{
            group_uuid: UUID, name: 'research', position: 0,
            members: ['cloude_a'], member_session_uuids: ['s-a'],
            colour: 'teal', gradient: null, animation: 'none', style_source: 'stored', icon,
        }],
    });
    return window;
}


await test('an id this build does not know is kept in the store', () => {
    const w = stack('from-the-future');
    assert.equal(w.SessionSidebarGroupStore.groupByUuid(UUID).icon, 'from-the-future');
});

await test('a non-string icon from the wire is stored as none', () => {
    const w = stack(42);
    assert.equal(w.SessionSidebarGroupStore.groupByUuid(UUID).icon, null);
});

await test('a reserved band never draws a picked icon', () => {
    const w = stack('flask');
    assert.equal(w.SessionSidebarGroupIcon.headingMark(null), '');
});

await test('the group kebab offers "icon" right after "color", and it opens the icon popup', () => {
    const w = stack(null);
    const opened = [];
    w.SessionSidebarGroupIcon.open = (anchor, uuid) => opened.push(uuid);
    const anchor = w.document.createElement('button');
    w.SessionSidebarGroupActions.openGroupMenu(anchor, UUID);
    const menu = w.document.body.querySelector('.session-sidebar-group-menu');
    assert.ok(menu, 'setup: the menu opened');
    const labels = menu.innerHTML.match(/session-sidebar-group-menu__label">([^<]*)</g)
        .map((m) => m.replace(/.*">/, '').replace('<', ''));
    const colour = labels.indexOf('sidebar.group.colour.menu');
    const icon = labels.indexOf('sidebar.group.icon.menu');
    assert.ok(colour >= 0 && icon === colour + 1, `icon follows color: ${labels.join(', ')}`);
    const handlers = menu._listeners.get('click') || [];
    assert.equal(handlers.length, 1, 'setup: the menu listens for its own clicks');
    const picked = { getAttribute: (n) => (n === 'data-menu-index' ? String(icon) : null) };
    handlers[0]({ target: { closest: () => picked }, preventDefault() {}, stopPropagation() {} });
    assert.deepEqual(opened, [UUID], 'choosing "icon" opens the icon popup for this group');
});

const { passes, failures } = results();
console.log(`${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
