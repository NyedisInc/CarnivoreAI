/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { afterEach, beforeAll, beforeEach, describe, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Search from '../drawer/search';
import * as Store from '../drawer/store';
import * as GroupStore from '../drawer/group-store';
import * as EmptySections from '../drawer/empty-sections.svelte';

beforeAll(() => { loadLegacyDrawer(); });

function applyGroups(): void {
    GroupStore.apply({
        status: 'ok',
        groups: [
            { group_uuid: 'g1', name: 'alpha crew', position: 0, members: ['cloude_a'] },
            { group_uuid: 'g2', name: 'beta crew', position: 1, members: ['cloude_b'] },
        ],
    });
}

beforeEach(() => {
    EmptySections.setEmptySectionsHidden(true);
    resetDrawer();
    Density.setMode('compact');
    applyGroups();
});

function row(name: string): Record<string, unknown> {
    return {
        name, label: name, status: 'idle', unread: false, is_pinned: false, project_id: 10, project_name: 'Foo',
        created_by_cloude: true, session_id: `ses_${name}`, session_uuid: `su-${name}`, kind: 'agent',
    };
}

function draw(rows: Record<string, unknown>[], query = '', dragging = false): string {
    Store.save([], rows.map((r) => r.name as string), []);
    Search.setQuery(query);
    return drawList(rows, { _dragging: dragging });
}

const has = (html: string, key: string): boolean => html.includes(`data-group="${key}"`);

it('a hand-made group with no member row stays drawn even when hide empty sections is on (#3373)', () => {
    const html = draw([row('cloude_a'), row('cloude_c')]);
    assert.ok(has(html, 'g:g1'), 'the group with a member draws');
    assert.ok(has(html, 'g:g2'), 'the empty hand-made group stays visible');
    assert.ok(html.includes('beta crew'), 'its heading is reachable to set rules or file rows');
});

it('the stored group stays intact as members come and go', () => {
    const before = JSON.stringify(GroupStore.current());
    assert.ok(has(draw([row('cloude_a')]), 'g:g2'));
    assert.ok(has(draw([row('cloude_a'), row('cloude_b')]), 'g:g2'));
    assert.equal(JSON.stringify(GroupStore.current()), before, 'drawing never edits the group store');
});

it('a group whose members were filtered out by view filters still stays drawn outside search (#3373)', () => {
    assert.ok(has(draw([row('cloude_a')]), 'g:g2'));
});

it('a typed search draws no group at all: the matching agent is listed flat, and a drag keeps the group it matches', () => {
    const html = draw([row('cloude_a'), row('cloude_b')], Search.normalize('cloude_a'));
    assert.ok(!has(html, 'g:g1') && !has(html, 'g:g2'), 'AGENTS is flat: no group headings');
    assert.ok(html.includes('data-group="search:agents"'));
    const dragged = draw([row('cloude_a'), row('cloude_b')], Search.normalize('cloude_a'), true);
    assert.ok(has(dragged, 'g:g1'), 'a drag keeps the text and the narrowed sections');
});

it('a drag in flight keeps an empty group as a drop target', () => {
    assert.ok(has(draw([row('cloude_a')], '', true), 'g:g2'));
});

it('the kind sections still draw with nothing in them', () => {
    EmptySections.setEmptySectionsHidden(false);
    const html = draw([row('cloude_a')]);
    assert.ok(has(html, 'terminals'), 'TERMINALS stays (#1804)');
    assert.ok(has(html, 'browsers'), 'BROWSERS stays (#1804)');
});

describe('the hide empty sections setting', () => {
    beforeEach(() => { EmptySections.setEmptySectionsHidden(false); });
    afterEach(() => { EmptySections.setEmptySectionsHidden(false); });

    it('off (the default) draws the empty TERMINALS and BROWSERS sections with their dim line', () => {
        EmptySections.init();
        assert.equal(EmptySections.emptySectionsHidden(), false, 'absent means off');
        const html = draw([row('cloude_a')]);
        assert.ok(has(html, 'terminals') && has(html, 'browsers'));
        assert.ok(html.includes('no terminals open'));
    });

    it('on hides the empty TERMINALS and BROWSERS sections, and a terminal row brings TERMINALS back', () => {
        EmptySections.setEmptySectionsHidden(true);
        const html = draw([row('cloude_a')]);
        assert.ok(!has(html, 'terminals') && !has(html, 'browsers'));
        const withShell = draw([row('cloude_a'), { ...row('cloude_t'), agent_family: 'shell', working_dir: '/Users/x/dev', project_id: null }]);
        assert.ok(has(withShell, 'terminals'), 'a section with a row draws');
        assert.ok(!has(withShell, 'browsers'));
    });

    it('both off and on keep a hand-made group with no member row visible (#3373)', () => {
        EmptySections.setEmptySectionsHidden(false);
        assert.ok(has(draw([row('cloude_a')]), 'g:g2'), 'off: the empty group draws');
        EmptySections.setEmptySectionsHidden(true);
        assert.ok(has(draw([row('cloude_a')]), 'g:g2'), 'on: the empty group stays visible');
        assert.ok(has(draw([row('cloude_a')]), 'g:g1'), 'a group with a member always draws');
    });

    it('on plus a drag in flight draws them as today', () => {
        EmptySections.setEmptySectionsHidden(true);
        const html = draw([row('cloude_a')], '', true);
        assert.ok(has(html, 'terminals') && has(html, 'browsers'));
    });

    it('the choice is read back from this browser and shared field, and absent stays off', () => {
        EmptySections.setEmptySectionsHidden(true);
        EmptySections.setEmptySectionsHidden(false);
        localStorage.removeItem(EmptySections.STORAGE_KEY);
        EmptySections.init();
        assert.equal(EmptySections.emptySectionsHidden(), false);
        localStorage.setItem(EmptySections.STORAGE_KEY, '1');
        EmptySections.init();
        assert.equal(EmptySections.emptySectionsHidden(), true);
    });
});
