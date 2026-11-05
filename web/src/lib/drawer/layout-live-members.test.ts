/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from 'vitest';
import { setDrawerEnv } from './env';
import { load } from './fetch';
import { init, setSectionShown } from './section-visibility.svelte';
import * as Layouts from './layouts-model';

const live = (name: string, rowId: number, label: string) => ({ tmux_session: name, label, agent_family: 'claude', session_row_id: rowId, session: { id: `ses_${rowId}`, working_dir: '/x' } });
const rec = (id: number, uuid: string, name: string, epoch: number) => ({ id, session_uuid: uuid, tmux_name: name, tmux_created_epoch: epoch, lifecycle: 'running' });
const asleepRec = { id: 120, session_uuid: 'u-asleep', tmux_name: 'carnivore_Orion-2', tmux_created_epoch: 1, lifecycle: 'stopped', asleep: true };

afterEach(() => { setDrawerEnv(null); vi.restoreAllMocks(); });

it('lists every member of a Layout while the view menu hides the open sessions', async () => {
    const API = {
        listAttachableSessions: async () => [],
        listSessions: async () => [live('carnivore_Orion-3', 121, 'Argent-CVEs'), live('carnivore_Orion-4', 122, 'Argent-Logs')],
        listSessionRecords: async () => [asleepRec, rec(121, 'u-3', 'carnivore_Orion-3', 11), rec(122, 'u-4', 'carnivore_Orion-4', 12)],
        listSessionCompanions: async () => [],
    };
    const store: Record<string, unknown> = {};
    const PreferenceBridge = { read: (f: string, fb: () => unknown) => (f in store ? store[f] : fb()), write: vi.fn(async (f: string, v: unknown, local: () => void) => { store[f] = v; local(); }) };
    setDrawerEnv({ PreferenceBridge }); init(); setSectionShown('open', false);
    const members = ['u-asleep', 'u-3', 'u-4'].map((session_uuid) => ({ session_uuid }));
    setDrawerEnv({ PreferenceBridge, API, CloudeWeb: { layouts: { list: () => [{ layout_uuid: 'L', name: 'Orion', colour: 'teal', gradient: null, animation: 'none', created_at: '2026-01-01T00:00:00Z', members }] } }, SessionSidebarLayouts: Layouts });
    const { rows } = await load(null);
    const layout = rows.find((r) => (r as { kind?: string }).kind === 'layout') as unknown as { member_count: number; _members: Array<{ name: string }> };
    expect(rows.map((r) => r.name)).not.toContain('carnivore_Orion-3');
    expect(layout.member_count).toBe(3);
    expect(layout._members.map((m) => m.name).sort()).toEqual(['carnivore_Orion-2', 'carnivore_Orion-3', 'carnivore_Orion-4']);
});

it('lists a member whose live row has no joinable uuid, by session_row_id, with both filters on', () => {
    const rows = [{ name: 'carnivore_Carnivore_ai', session_row_id: 197, session_uuid: null }, { name: 'other', session_uuid: 'u-o' }];
    const L = { layout_uuid: 'L', name: 'Carnivore', colour: 'teal', gradient: null, animation: 'none', created_at: '2026-01-01T00:00:00Z', members: [{ session_uuid: 'u-197', session_row_id: 197 }, { session_uuid: 'u-o', session_row_id: 5 }] };
    setDrawerEnv({ CloudeWeb: { layouts: { list: () => [L] } } });
    const out = Layouts.rows(rows)[0];
    expect(out._members.map((m) => m.name)).toEqual(['carnivore_Carnivore_ai', 'other']);
});
