/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { setViewClassSource } from './view-class';
import { setDrawerController } from './controller-ref';
import { closedShown, init } from './closed-visibility.svelte';
import { load } from './fetch';
import { arrange, move, placeAt, togglePin } from './arrangement';
import { matchesRow, setQuery } from './search';
import { current, save } from './store';

const rec = (over: Record<string, unknown>) => ({ agent_family: 'claude', project_id: 1, project_name: 'p', working_dir: '/x', ...over });
const records = [rec({ session_uuid: 'u-ha', tmux_name: 'carnivore_homeassistant', closed: true, lifecycle: 'stopped', title: 'Home Assistant' })];

beforeEach(() => {
    localStorage.clear(); setDrawerEnv(null); setViewClassSource(() => 'desktop'); init();
    setDrawerController({ repaint: vi.fn(), refreshNow: vi.fn() } as never);
    (globalThis as Record<string, unknown>).API = {
        listAttachableSessions: async () => [], listSessions: async () => [],
        listSessionRecords: async () => records, listSessionCompanions: async () => [],
    };
    save([], []);
});
afterEach(() => {
    setQuery(''); setViewClassSource(null); setDrawerEnv(null); setDrawerController(null); vi.restoreAllMocks();
    delete (globalThis as Record<string, unknown>).API;
});

it('a query matching a hidden closed row returns it, with show closed off', async () => {
    expect(closedShown()).toBe(false);
    setQuery('home');
    const { rows } = await load(null);
    const hit = rows.filter((r) => matchesRow(r, 'home'));
    expect(hit.map((r) => r.name)).toEqual(['carnivore_homeassistant']);
    expect(hit[0]).toMatchObject({ closed: true, session_uuid: 'u-ha' });
});

it('an empty query keeps the closed row hidden', async () => {
    expect((await load(null)).rows.map((r) => r.name)).toEqual([]);
});

it('clearing the query hides the closed row again', async () => {
    setQuery('home');
    expect((await load(null)).rows).toHaveLength(1);
    setQuery('');
    expect((await load(null)).rows).toHaveLength(0);
});

it('a pinned closed row shows in the pinned band with show closed off, found by name or by the uuid its pin was filed under', async () => {
    expect(closedShown()).toBe(false);
    save(['carnivore_homeassistant'], []);
    const byName = arrange((await load(null)).rows as never);
    expect(byName.rows.map((r) => [r.name, r.is_pinned, r.band_key])).toEqual([['carnivore_homeassistant', true, 'pinned']]);
    save(['carnivore_old_name'], [], undefined, { carnivore_old_name: 'u-ha' });
    expect(current().ids).toMatchObject({ carnivore_old_name: 'u-ha' });
    expect((await load(null)).rows.map((r) => r.session_uuid)).toEqual(['u-ha']);
});

it('pinning a closed hit from a search keeps it in the pinned band after the query clears, show closed off', async () => {
    setQuery('home');
    const hits = (await load(null)).rows.map((r) => r.name as string);
    expect(togglePin('carnivore_homeassistant', hits)).toBe(true);
    setQuery('');
    expect(closedShown()).toBe(false);
    const after = arrange((await load(null)).rows as never);
    expect(after.rows.map((r) => [r.name, r.band_key])).toEqual([['carnivore_homeassistant', 'pinned']]);
});

it('a pin from a search leaves the saved order alone (the hits are in match order, not the saved order)', () => {
    save([], ['a', 'b', 'c']);
    setQuery('x');
    expect(togglePin('c', ['c', 'a'])).toBe(true);
    expect(current().order).toEqual(['a', 'b', 'c']);
    expect(current().pinned).toEqual(['c']);
    expect(togglePin('c', ['c', 'a'])).toBe(false);
    expect(current().order).toEqual(['a', 'b', 'c']);
    setQuery('');
    togglePin('c', ['c', 'a']);
    expect(current().order).toEqual(['c', 'b', 'a']);
});

it('a keyboard or drag move during a search leaves the saved order alone too', () => {
    save([], ['a', 'b', 'c']);
    setQuery('x');
    expect(move('a', -1, ['c', 'a', 'b'])?.order).toEqual(['a', 'c', 'b']);
    expect(current().order).toEqual(['a', 'b', 'c']);
    expect(placeAt('b', false, 'c', ['c', 'a', 'b'])?.order).toEqual(['b', 'c', 'a']);
    expect(current().order).toEqual(['a', 'b', 'c']);
    setQuery('');
    move('c', -1, ['a', 'b', 'c']);
    expect(current().order).toEqual(['a', 'c', 'b']);
});
