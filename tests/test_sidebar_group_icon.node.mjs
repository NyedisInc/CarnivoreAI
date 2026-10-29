// and the real
import assert from 'node:assert/strict';
import { glyphSvg } from '../client/js/icons/glyphs.js';
import { iconSvg } from '../client/js/icons/icon-registry.js';
import { Doc, fakeStorage, loadModules, results, test } from './lib-sidebar-sessions.mjs';

const BASE = [
    'status-led.js', 'session-status-summary.js',
    'session-sidebar-store-keys.js', 'session-sidebar-store.js', 'session-sidebar-arrangement.js',
    'session-sidebar-group-membership.js', 'session-sidebar-group-store.js',
    'session-sidebar-search.js', 'session-sidebar-groups-search.js',
    'session-sidebar-fetch.js',
    'session-row-menu-icons.js',
];

const UUID = 'g-1';
const KEY = `g:${UUID}`;

function stack(icon) {
    const { window } = loadModules(BASE, { storage: fakeStorage({}), document: new Doc() });
    window.CloudeGlyphs = { glyphSvg, iconSvg };
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



const { passes, failures } = results();
console.log(`${passes} passed, ${failures} failed`);
if (failures) process.exit(1);
console.log('ALL PASS');
