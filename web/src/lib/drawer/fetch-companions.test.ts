/** @vitest-environment jsdom */
import { afterEach, expect, it, vi } from 'vitest';
import { terminalRows } from './bucketing';
import { load } from './fetch';

const agent = { tmux_session: 'cloude_a', agent_family: 'claude', session: { id: 'ses_a', working_dir: '/x' } };
const shell = { tmux_session: 'carnivore_sh-1', agent_family: 'shell', session: { id: 'ses_s', working_dir: '/x' } };

function api(companions: () => Promise<unknown>): void {
    (globalThis as Record<string, unknown>).API = {
        listAttachableSessions: async () => [],
        listSessions: async () => [agent],
        listSessionRecords: async () => [],
        listSessionCompanions: companions,
    };
}

afterEach(() => { delete (globalThis as Record<string, unknown>).API; vi.restoreAllMocks(); });

it('a companion from its own collection lists under TERMINALS; the live list never carried it', async () => {
    api(async () => [shell]);
    const { rows } = await load(null);
    expect(rows.map((r) => r.name).sort()).toEqual(['carnivore_sh-1', 'cloude_a']);
    expect(terminalRows(rows as never).map((r) => r.name)).toEqual(['carnivore_sh-1']);
});

it('a failing companion read leaves the list intact', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    api(async () => { throw new Error('404'); });
    expect((await load(null)).rows.map((r) => r.name)).toEqual(['cloude_a']);
});
