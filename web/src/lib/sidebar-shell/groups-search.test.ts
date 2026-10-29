/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, beforeEach, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Store from '../drawer/store';
import * as Search from '../drawer/search';
import * as GroupStore from '../drawer/group-store';

beforeAll(() => {
    loadLegacyDrawer();
});

function applyGroups(): void {
    GroupStore.apply({
        status: 'ok',
        groups: [{ group_uuid: 'g1', name: 'work stuff', position: 0, members: ['cloude_lantern_app'] }],
    });
}

beforeEach(() => {
    resetDrawer();
    Density.setMode('compact');
    applyGroups();
});

function draw(rows: Record<string, any>[], query: string, dragging = false): string {
    Store.save(rows.filter((r) => r.is_pinned).map((r) => r.name), rows.map((r) => r.name), []);
    Search.setQuery(query);
    return drawList(rows, { _dragging: !!dragging });
}

function fixtureRows() {
    return [
        {
            name: 'cloude_lantern_app', label: 'Lantern App', is_pinned: true,
            project_id: 10, project_name: 'ProjectFoo', status: 'idle',
            created_by_cloude: true, session_id: null,
        },
        {
            name: 'cloude_argent', label: null, is_pinned: false,
            project_id: 10, project_name: 'ProjectFoo', status: 'idle',
            created_by_cloude: true, session_id: null,
        },
        {
            name: 'cloude_atlas_ui', label: 'Atlas-UI', is_pinned: false,
            project_id: 20, project_name: 'Design', status: 'idle',
            created_by_cloude: true, session_id: null,
        },
        {
            name: 'cloude_carnivore_share', label: 'Carnivore-Share', is_pinned: false,
            project_id: 20, project_name: 'Design', status: 'idle',
            created_by_cloude: true, session_id: null,
        },
        {
            name: 'cloude_rogue_one', label: null, is_pinned: false,
            project_id: null, project_name: null, status: 'idle',
            created_by_cloude: true, session_id: null,
        },
    ];
}

function namesIn(html: string): string[] {
    return [...new Set([...html.matchAll(/data-name="([^"]+)"/g)].map((m) => m[1] as string))];
}

function body(query: string, dragging?: boolean): string {
    return draw(fixtureRows(), query, !!dragging);
}

it('no query: the ordinary, unfiltered picture - every row, PINNED + its group + its project, each rendered once per section', async () => {
    const html = body('');
    assert.deepEqual(
        namesIn(html).sort(),
        ['cloude_argent', 'cloude_carnivore_share', 'cloude_atlas_ui', 'cloude_lantern_app', 'cloude_rogue_one'].sort(),
    );
    assert.equal((html.match(/data-name="cloude_lantern_app"/g) || []).length, 3);
    assert.ok(html.includes('work stuff'));
    assert.ok(html.includes('ProjectFoo'));
    assert.ok(html.includes('Design'));
});

it('filter by SESSION DISPLAY NAME: the matching row is listed ONCE, under AGENTS, with no section headings around it', async () => {
    const html = body(Search.normalize('argent'));
    assert.deepEqual(namesIn(html), ['cloude_argent']);
    assert.equal((html.match(/data-name="cloude_argent"/g) || []).length, 1);
    assert.ok(html.includes('data-group="search:agents"'), 'the flat AGENTS section');
    assert.ok(!html.includes('data-group="pinned"') && !html.includes('work stuff') && !html.includes('Design'));
});

it('filter by TMUX NAME: matches the handle even when a label hides it from the display name', async () => {
    const html = body(Search.normalize('lantern_app'));
    assert.deepEqual(namesIn(html), ['cloude_lantern_app']);
});

it('a PROJECT NAME matches: every agent in that project is listed, each once', async () => {
    const html = body(Search.normalize('ProjectFoo'));
    assert.deepEqual(namesIn(html).sort(), ['cloude_argent', 'cloude_lantern_app']);
    assert.equal((html.match(/data-name="cloude_lantern_app"/g) || []).length, 1, 'a pinned hit is listed once, not under PINNED and its project');
});

it('a GROUP NAME no longer keeps its members: a header match is not a session name', async () => {
    const html = body(Search.normalize('work stuff'));
    assert.deepEqual(namesIn(html), []);
});

it('"pinned" does not keep PINNED: only a row that matches is listed, and a pinned one wears no pin', async () => {
    const html = body(Search.normalize('pin'));
    assert.deepEqual(namesIn(html), []);
    const named = body(Search.normalize('lante'));
    assert.ok(named.includes('data-group="search:agents"'));
    assert.ok(!named.includes('oc-tag') && !named.includes('data-pin-session'), 'a pinned hit draws no pin in a search');
});

it('a saved Layout row and a browser row in a search draw no pin, keep the kebab; the normal drawer keeps both pins', async () => {
    const extra = [
        {
            name: 'layout:l1', kind: 'layout', layout_uuid: 'l1', label: 'Main Layout', member_count: 0, member_names: [], _members: [],
            created_at_epoch: 0, last_work_at: null, project_id: null, project_name: null, working_dir: null,
        },
        {
            name: 'browser:0123456789abcdef', kind: 'browser', label: 'Main Browser', status: 'idle', host: 'example.com',
            project_id: null, project_name: null, session_id: null,
        },
    ];
    const rows = [...fixtureRows(), ...extra];
    const searched = draw(rows, Search.normalize('main'));
    assert.ok(searched.includes('Main Layout') && searched.includes('Main Browser'), 'both rows are search hits');
    assert.ok(searched.includes('data-search-section'), 'the agents section is drawn');
    assert.ok(searched.includes('data-row-menu'), 'the kebab stays');
    assert.match(searched, /session-sidebar-row-name"[^>]*><mark class="sd-mark">Main<\/mark> Layout/, 'the match is marked in the layout name');
    assert.ok(searched.includes('session-sidebar-row-subtitle'), 'the muted member count stays at the right');
    assert.ok(searched.includes('session-sidebar-row-provider'), 'the layout glyph sits in the light slot');
    const agents = searched.slice(searched.indexOf('data-search-section'));
    const browserRow = agents.slice(agents.indexOf('Main Browser') - 600, agents.indexOf('Main Browser') + 600);
    assert.ok(!browserRow.includes('session-sidebar-row-pin'), 'a browser hit draws no pin');
    const normal = draw(rows, '');
    assert.ok(normal.includes('session-sidebar-row-pin'), 'the normal drawer keeps its pins');
});

it('empty groups hide: nothing in Design or the rogue bucket matches "argent", so neither section appears at all', async () => {
    const html = body(Search.normalize('argent'));
    assert.ok(!html.includes('Design'));
    assert.ok(!html.includes('rogue'));
});

it('a query with nothing that matches renders no agent, and the list offers the next steps', async () => {
    const q = Search.normalize('zzz-nothing-on-this-list-zzz');
    const html = body(q);
    assert.ok(html.includes('data-testid="search-nomatch"'), 'the no-match state with its next steps');
    assert.match(html, /nothing matches/);
    assert.ok(html.includes('data-search-next="conversations"') && html.includes('data-search-next="clear"'));
    assert.ok(!html.includes('data-name='), 'no row markup at all, not even a hidden one');
});

it('an empty query renders the ordinary body through the list too - no "no matches" line when nothing was asked for', async () => {
    const html = body('');
    assert.ok(!html.includes('data-search-empty'));
    assert.deepEqual(namesIn(html).length, 5);
});

it('a drag in flight keeps the query and the sections, so the empty-pinned drop target is never eaten by an unrelated filter', async () => {
    const html = body(Search.normalize('nothing-matches-anything'), true);
    assert.ok(html.includes('data-group="pinned"'), 'the empty pinned drop target must still draw while dragging');
});

it('filtering never mutates saved state: the group store and the row fixtures are unchanged by any of the above', async () => {
    const before = JSON.stringify(GroupStore.current());
    body(Search.normalize('argent'));
    body(Search.normalize('work stuff'));
    body('');
    assert.equal(JSON.stringify(GroupStore.current()), before, 'no query may touch the group store');
    const rows = fixtureRows();
    draw(rows, '');
    const snapshot = JSON.stringify(rows);
    draw(rows, Search.normalize('argent'));
    assert.equal(JSON.stringify(rows), snapshot, 'filtering must not write is_pinned, band_key or anything else onto a row');
});

