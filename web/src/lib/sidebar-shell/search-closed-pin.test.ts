/** @vitest-environment jsdom */
import assert from 'node:assert/strict';
import { beforeAll, beforeEach, afterEach, expect, it } from 'vitest';
import { loadRowInteractions, settle } from './row-interaction-fixture';
import { play, ROW } from './row-interaction-play';
import { sidebarShell } from './shell.svelte';
import { drawList, loadLegacyDrawer, resetDrawer } from './legacy-fixture';
import * as Density from '../drawer/density';
import * as Search from '../drawer/search';
import * as Store from '../drawer/store';
import { searchD } from '../drawer/search-d.svelte';
import { current } from '../drawer/store';

beforeAll(() => { loadLegacyDrawer(); });
beforeEach(() => { resetDrawer(); Density.setMode('compact'); });
afterEach(() => { Search.setQuery(''); searchD.actions = null; });

function row(name: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
    return { name, label: null, is_pinned: false, project_id: 10, project_name: 'Carnivore', working_dir: '/x/carnivore', status: 'idle', created_by_cloude: true, session_id: null, session_uuid: `uuid-${name}`, ...extra };
}

for (const mode of ['compact', 'cozy', 'detailed'] as const) {
    it(`a session hit draws at ${mode} density, as the same row outside a search`, () => {
        Density.setMode(mode);
        const rows = [row('cloude_carn_a', { running_model: 'claude-opus-4-6' })];
        const plain = drawList(rows);
        Search.setQuery('carn');
        const hit = drawList(rows);
        const bodyKind = (html: string) => /data-row-body="(cozy|detailed)"/.exec(html)?.[1] ?? 'compact';
        assert.equal(bodyKind(hit), mode);
        assert.equal(bodyKind(plain), mode);
        assert.ok(hit.includes('data-search-hit="1"') && hit.includes('session-sidebar-row-main'));
    });
}

it('every session hit has a pin button, shown even when the pin row-icon is off', () => {
    Search.setQuery('carn');
    const html = drawList([row('cloude_carn_a'), row('cloude_carn_b', { closed: true })]);
    assert.equal((html.match(/data-pin-session=/g) || []).length, 2);
});

it('the hit pin pins and unpins the session through the one arrangement, a pinned hit showing as pressed', async () => {
    const w = loadRowInteractions(sidebarShell);
    const hitPin = `[data-search-section="agents"] ${ROW('cloude_c')} [data-pin-session]`;
    await play(w, async (g) => {
        Search.setQuery('c');
        await settle();
        expect(g.has(hitPin)).toBe(true);
        expect(document.querySelector(hitPin)?.getAttribute('aria-pressed')).toBe('false');
        await g.click(hitPin);
        expect(current().pinned).toContain('cloude_c');
        expect(document.querySelector(hitPin)?.getAttribute('aria-pressed')).toBe('true');
        await g.click(hitPin);
        expect(current().pinned).not.toContain('cloude_c');
    });
});

it('the session hits are capped at 50, with a muted line naming how many are hidden', () => {
    Search.setQuery('carn');
    const rows = Array.from({ length: 60 }, (_, i) => row(`cloude_carn_${String(i).padStart(2, '0')}`));
    const html = drawList(rows);
    assert.equal((html.match(/class="session-sidebar-row"/g) || []).length, 50);
    assert.match(html, /<p class="ssr-line" data-search-more(="")?>10 more agents, type more to narrow<\/p>/);
    assert.match(html, /<span class="sd-hd__n">60<\/span>/, 'the head counts every hit');
    assert.ok(!drawList(rows.slice(0, 50)).includes('data-search-more'));
    assert.match(drawList(rows.slice(0, 51)), /data-search-more(="")?>1 more agent, type more/);
});

it('a closed hit\'s pin names its title, never closed:<uuid>', () => {
    Search.setQuery('home');
    const html = drawList([row('closed:u-1', { closed: true, label: 'Home Assistant' }), row('cloude_home_b', { label: 'Home B' })]);
    assert.match(html, /aria-label="pin Home Assistant to the top"/);
    assert.match(html, /aria-label="pin Home B to the top"/, 'a live row speaks its display name, not the tmux name');
});
