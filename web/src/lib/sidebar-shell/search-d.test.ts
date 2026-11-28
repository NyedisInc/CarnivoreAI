/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { flushSync } from 'svelte';
import { beforeAll, beforeEach, afterEach, it } from 'vitest';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Search from '../drawer/search';
import * as Store from '../drawer/store';
import { searchD } from '../drawer/search-d.svelte';
import { searchHitRows } from './search-plan';

beforeAll(() => {
    loadLegacyDrawer();
});
beforeEach(() => {
    resetDrawer();
    Density.setMode('compact');
});
afterEach(() => {
    Search.setQuery('');
    searchD.actions = null;
});

function row(name: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { name, label: null, is_pinned: false, project_id: 10, project_name: 'Carnivore', working_dir: '/Users/x/dev/carnivore', status: 'idle', created_by_cloude: true, session_id: null, ...extra };
}

const namesIn = (html: string): string[] => [...html.matchAll(/data-name="([^"]+)"/g)].map((m) => m[1] as string);

it('matches a name, a project, a folder and an asleep row, best match first', () => {
    const rows = [
        row('cloude_billing', { project_name: 'Ledger', working_dir: '/Users/x/dev/carnage' }),
        row('cloude_carn_docs', { asleep: true, project_name: 'Ledger', working_dir: '/tmp/a' }),
        row('cloude_zed', { project_name: 'Carnival', working_dir: '/tmp/z' }),
        row('cloude_other', { project_name: 'Ledger', working_dir: '/Users/x/dev/carnet' }),
    ];
    assert.deepEqual(searchHitRows(rows as never, 'carn').map((r) => r.name), ['cloude_carn_docs', 'cloude_zed', 'cloude_billing', 'cloude_other']);
});

it('a pinned hit is listed ONCE, wears its pressed pin (no tag), keeps its menu key, and the sections give way to AGENTS', () => {
    Search.setQuery('carn');
    const rows = [row('cloude_carn_a', { is_pinned: true }), row('cloude_carn_b')];
    Store.save(['cloude_carn_a'], rows.map((r) => r.name as string), []);
    const html = drawList(rows);
    assert.deepEqual(namesIn(html), ['cloude_carn_a', 'cloude_carn_b']);
    assert.ok(html.includes('data-group="search:agents"'));
    assert.ok(!html.includes('data-group="pinned"') && !html.includes('data-group="p:10"'));
    assert.equal((html.match(/oc-tag/g) || []).length, 0, 'a search result wears no pinned tag');
    assert.match(html, /data-pin-session="cloude_carn_a" aria-pressed="true"/, 'a pinned hit shows as pinned');
    assert.match(html, /data-pin-session="cloude_carn_b" aria-pressed="false"/, 'an unpinned hit offers the pin');
    assert.ok(html.includes('session-row-menu-trigger'), 'the kebab stays');
});

it('the match is marked in the name, and a project or folder match says why the row is listed', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a'), row('cloude_other', { project_name: 'Carnival', working_dir: '/tmp/z' })]);
    assert.match(html, /<mark class="sd-mark">carn<\/mark>/);
    assert.match(html, /sd-why/);
    assert.match(html, /<mark class="sd-mark">Carn<\/mark>ival/);
});

it('an agent row in a search is just the result: no open or look-around buttons, one click is the open', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a', { asleep: true, claude_session_uuid: 'conv-1' }), row('cloude_carn_b')]);
    assert.ok(html.includes('data-name="cloude_carn_a"') && html.includes('data-name="cloude_carn_b"'), 'both rows are listed');
    assert.ok(!html.includes('data-search-action'), 'no button on an agent row');
    assert.ok(!html.includes('session-sidebar-row-search__acts'));
});

it('a drag keeps the text: the sections come back narrowed, the drop targets stay', () => {
    Search.setQuery('carn');
    const rows = [row('cloude_carn_a', { is_pinned: true }), row('cloude_zzz', { project_name: 'Ledger', working_dir: '/tmp/z' })];
    Store.save(['cloude_carn_a'], rows.map((r) => r.name as string), []);
    const html = drawList(rows, { _dragging: true });
    assert.ok(!html.includes('data-group="search:agents"'));
    assert.ok(html.includes('data-group="pinned"') && html.includes('data-group="p:10"'));
    assert.deepEqual([...new Set(namesIn(html))], ['cloude_carn_a'], 'the row that does not match is narrowed away');
});

it('nothing matching offers the next steps: search the conversations, or clear', () => {
    Search.setQuery('zzz-nothing');
    searchD.controller = null;
    const html = drawList([row('cloude_a')]);
    assert.ok(html.includes('data-testid="search-nomatch"'));
    assert.ok(html.includes('data-search-next="conversations"') && html.includes('data-search-next="clear"'));
    assert.ok(!html.includes('data-name='));
});

it('the no-match line names the typed text, and follows the mode: names speaks of agents only, all adds saved conversations', () => {
    Search.setQuery('tmux');
    searchD.controller = null;
    const names = drawList([row('cloude_a')]);
    assert.ok(names.includes('nothing matches "tmux" in agents.'), 'names mode: the typed text, agents only');
    assert.ok(!names.includes('saved conversations'));
    searchD.controller = { query: 'tmux', phase: 'done', total: 0, groups: [] } as never;
    const all = drawList([row('cloude_a')]);
    assert.ok(all.includes('nothing matches "tmux" in agents or saved conversations.'), 'all mode: the typed text, both');
    searchD.controller = null;
});

it('a typed text lists sleeping rows whatever the view menu says; clearing it restores the filter', () => {
    assert.equal(Search.searchLists(), false);
    Search.setQuery('carn');
    assert.equal(Search.searchLists(), true);
    Search.setQuery('');
    assert.equal(Search.searchLists(), false);
});

it('the folder match is the folder\'s own name, never its parent directories', () => {
    const rows = [
        row('cloude_fantasy', { name: 'cloude_fantasy', label: 'Fantasy Hockey', project_name: 'Sports', working_dir: '/Users/x/carnivore-projects/fantasy-hockey' }),
        row('cloude_app', { project_name: 'Ledger', working_dir: '/a/b/carnivore-app/' }),
    ];
    assert.deepEqual(searchHitRows(rows as never, 'carn').map((r) => r.name), ['cloude_app']);
});

it('matches a tmux handle without its owned product prefix: "carn" and "clou" list no agent for the prefix alone', () => {
    const q = (text: string) => Search.normalize(text);
    const hockey = { name: 'carnivore_fantasy_hockey', label: 'Fantasy Hockey', working_dir: '/x/fantasy-hockey' };
    const wrapper = { name: 'carnivore_carnivore_wrapper', label: 'Carnivore - Wrapper' };
    const legacy = { name: 'cloude_api' };
    assert.equal(Search.matchesRow(hockey, q('carn')), false, 'the carnivore_ prefix alone is not a match');
    assert.equal(Search.matchesRow(wrapper, q('carn')), true, 'a name that really says carnivore still matches');
    assert.equal(Search.matchesRow(legacy, q('clou')), false, 'the legacy cloude_ prefix alone is not a match');
    assert.equal(Search.matchesRow(hockey, q('fantasy_hockey')), true, 'the rest of the handle still matches');
});

it('a session hit is the drawer\'s own session row: the status-icon cluster, the provider mark, the kebab and the pin, marked as a search hit', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a', { agent_family: 'claude' })]);
    assert.ok(html.includes('session-sidebar-row-main') && html.includes('session-sidebar-row-controls-cluster'));
    assert.ok(html.includes('data-search-hit="1"') && html.includes('session-row-menu-trigger') && html.includes('session-sidebar-row-pin'));
    assert.ok(!html.includes('sd-r__body'), 'the quiet D row is gone');
});

it('a closed hit wears the closed chip and no status light, like a closed row outside the search', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_b', { closed: true })]);
    assert.ok(html.includes('session-sidebar-row-closed'), 'the closed chip');
    assert.ok(!html.includes('dps__led'), 'a closed row has no light');
});

it('the section head is a fold chevron, the name and the muted count, as variant D draws it', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a'), row('cloude_carn_b')]);
    assert.match(html, /<div class="sd-hd"><button type="button" class="sd-hd__fold" aria-expanded="true"[^>]*><span class="sd-hd__chev">/);
    assert.match(html, /<span class="sd-hd__label">agents<\/span><span class="sd-hd__n">2<\/span>/);
    assert.ok(!html.includes('ssr-strip'), 'the old label strip is gone');
});
