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

it('a pinned hit is listed ONCE, draws no pin (no tag, no pin toggle), keeps its menu key, and the sections give way to AGENTS', () => {
    Search.setQuery('carn');
    const rows = [row('cloude_carn_a', { is_pinned: true }), row('cloude_carn_b')];
    Store.save(['cloude_carn_a'], rows.map((r) => r.name as string), []);
    const html = drawList(rows);
    assert.deepEqual(namesIn(html), ['cloude_carn_a', 'cloude_carn_b']);
    assert.ok(html.includes('data-group="search:agents"'));
    assert.ok(!html.includes('data-group="pinned"') && !html.includes('data-group="p:10"'));
    assert.equal((html.match(/oc-tag/g) || []).length, 0, 'a search result wears no pinned tag');
    assert.ok(!html.includes('session-sidebar-row-pin') && !html.includes('data-pin-session'), 'a search result draws no pin toggle');
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

it('an agent row in a search is the quiet D row: no box chrome, provider mark, status-icon cluster, closed chip or pin, but the kebab, the age and the model line', () => {
    Search.setQuery('carn');
    const stamp = new Date(Date.now() - 3 * 3600 * 1000).toISOString();
    const html = drawList([row('cloude_carn_a', { running_model: 'claude-opus-4-6', running_model_effort: 'high', last_work_at: stamp, agent_family: 'claude' })]);
    assert.ok(html.includes('class="session-sidebar-row ssr-row sd-r"'), 'the quiet row, still a session row for the band gestures');
    for (const chrome of ['session-sidebar-row-main', 'session-sidebar-row-provider', 'session-sidebar-row-controls-cluster', 'session-sidebar-row-closed', 'session-sidebar-row-pin']) {
        assert.ok(!html.includes(chrome), `no ${chrome} on a search agent row`);
    }
    assert.ok(html.includes('session-row-menu-trigger'), 'the kebab stays at the end of line one');
    assert.match(html, /<span class="sd-r__meta">3h<\/span>/);
    assert.match(html, /class="sd-r__sub"><span class="session-sidebar-row-model/);
    assert.match(html, /<span>opus-4-6<\/span><span class="sd-dim">high<\/span>/);
});

it('a closed agent row still draws a light slot (the quiet ring), so its name starts in the same column as every other row (Joe, 2026-10-22)', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a'), row('cloude_carn_b', { closed: true })]);
    const closed = html.slice(html.indexOf('data-name="cloude_carn_b"'));
    const top = closed.slice(0, closed.indexOf('</div>'));
    assert.match(top, /class="dps__led dps__led--ring"/, 'the closed row wears a hollow ring in the light slot');
    assert.ok(top.indexOf('dps__led') < top.indexOf('session-sidebar-row-name'), 'the slot comes before the name');
});

it('an asleep agent says "asleep, worked ..." and a closed one "closed" on the muted second line, in place of the model, with no chip', () => {
    Search.setQuery('carn');
    const stamp = new Date(Date.now() - 2 * 86400 * 1000).toISOString();
    const asleep = drawList([row('cloude_carn_a', { asleep: true, running_model: 'claude-opus-4-6', last_work_at: stamp })]);
    assert.match(asleep, /<span class="sd-dim">asleep, worked 2d ago<\/span>/);
    assert.ok(!asleep.includes('opus-4-6'), 'the note stands in for the model line');
    const closed = drawList([row('cloude_carn_b', { closed: true })]);
    assert.match(closed, /<span class="sd-dim">closed<\/span>/);
    assert.ok(!closed.includes('session-sidebar-row-closed') && !closed.includes('session-sidebar-row-badge'), 'no closed chip box');
});

it('the section head is a fold chevron, the name and the muted count, as variant D draws it', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a'), row('cloude_carn_b')]);
    assert.match(html, /<div class="sd-hd"><button type="button" class="sd-hd__fold" aria-expanded="true"[^>]*><span class="sd-hd__chev">/);
    assert.match(html, /<span class="sd-hd__label">agents<\/span><span class="sd-hd__n">2<\/span>/);
    assert.ok(!html.includes('ssr-strip'), 'the old label strip is gone');
});
