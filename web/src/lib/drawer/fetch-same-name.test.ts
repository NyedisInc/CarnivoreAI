/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it } from 'vitest';
import { setDrawerEnv } from './env';
import { setViewClassSource } from './view-class';
import { init } from './closed-visibility.svelte';
import { load } from './fetch';

const NAME = 'carnivore_X';
const rec = (uuid: string, epoch: number, work: string) => ({
    session_uuid: uuid, tmux_name: NAME, tmux_created_epoch: epoch, asleep: true, lifecycle: 'asleep', last_work_at: work,
    agent_family: 'claude', project_id: 1, project_name: 'p', working_dir: '/x',
});

beforeEach(() => { localStorage.clear(); setDrawerEnv(null); setViewClassSource(() => 'desktop'); init(); });
afterEach(() => {
    setViewClassSource(null); setDrawerEnv(null);
    delete (globalThis as Record<string, unknown>).API;
});

it('a live external row resolved to one session keeps its name; the twin record still gets its own row and its own stamp', async () => {
    (globalThis as Record<string, unknown>).API = {
        listAttachableSessions: async () => [{ name: NAME, created_at_epoch: 200 }],
        listSessions: async () => [],
        listSessionRecords: async () => [rec('u1', 100, '2026-11-01T00:00:00Z'), rec('u2', 200, '2026-11-09T00:00:00Z')],
        listSessionCompanions: async () => [],
    };
    const rows = (await load(null)).rows;
    expect(rows.map((r) => r.name).sort()).toEqual(['asleep:u1', NAME]);
    const twin = rows.find((r) => r.name === 'asleep:u1')!;
    expect(twin.last_work_at).toBe('2026-11-01T00:00:00Z');
});

const API = (over: Record<string, unknown>) => {
    (globalThis as Record<string, unknown>).API = {
        listAttachableSessions: async () => [], listSessions: async () => [], listSessionCompanions: async () => [], ...over,
    };
};

it('a record with no stamp stays null; it never borrows the newest stamp across its tmux name (#2979)', async () => {
    API({ listSessionRecords: async () => [rec('u1', 100, ''), rec('u2', 200, '2026-11-09T00:00:00Z')] });
    const rows = (await load(null)).rows;
    expect(rows.map((r) => [r.session_uuid, r.last_work_at]).sort()).toEqual([['u1', null], ['u2', '2026-11-09T00:00:00Z']]);
});

it('a live row reads only its own record stamp, never the name-wide newest (#2979)', async () => {
    API({
        listAttachableSessions: async () => [{ name: NAME }],
        listSessions: async () => [{ tmux_session: NAME, session_uuid: 'u-live', agent_family: 'claude', session: { id: 'ses_l', working_dir: '/x' } }],
        listSessionRecords: async () => [rec('u-old', 100, '2026-11-09T00:00:00Z')],
    });
    const live = (await load(null)).rows.find((r) => r.name === NAME)!;
    expect(live.session_uuid).toBe('u-live');
    expect(live.last_work_at).toBeNull();
});

it('a closed twin\'s synthetic name never labels the row: the tmux name stays on the row for the label resolver (#2979)', async () => {
    API({ listSessionRecords: async () => [rec('u1', 100, ''), rec('u2', 200, '')] });
    const twin = (await load(null)).rows.find((r) => r.name === 'asleep:u2')!;
    expect(twin.tmux_name).toBe(NAME);
    expect(twin.label).toBeNull();
});
