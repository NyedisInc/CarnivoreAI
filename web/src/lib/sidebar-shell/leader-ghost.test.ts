/** @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const shown = vi.hoisted(() => ({ entries: [] as { label: string; run?: () => void }[] }));
const opened = vi.hoisted(() => vi.fn());
const calls = vi.hoisted(() => ({ turnOff: [] as unknown[][], ask: vi.fn(), wake: vi.fn(), refresh: vi.fn() }));
const openCalls = vi.hoisted(() => [] as unknown[][]);
vi.mock('../item-menu/open.svelte', () => ({ openItemMenu: (...a: unknown[]) => { openCalls.push(a); return true; }, closeItemMenu: () => {} }));
vi.mock('../../cplugs/sdk/swarm-agent-actions', () => ({
    wakeSwarmAgent: calls.wake, renameSwarmAgent: vi.fn(), turnOffSwarmAgent: async (...a: unknown[]) => { calls.turnOff.push(a); },
    openSwarmAgentTerminal: opened,
}));
vi.mock('../../cplugs/sdk/swarm-roster.svelte', () => ({ refreshSwarmRoster: calls.refresh }));
vi.mock('../leader-confirm/confirm', () => ({ askLeaderConfirm: calls.ask }));
vi.mock('../i18n/index.svelte', () => ({ t: (k: string) => k }));
import { openGhostMenu, openGhostTerminal, type GhostAgent } from './leader-ghost';
import '../item-menu/menus/leader';
import { itemMenu } from '../item-menu/registry';

function openMenu(g: GhostAgent): void {
    openGhostMenu(document.body, g);
    const [type, ctx] = openCalls.at(-1) as ['leader', { ghost: GhostAgent; anchor: Element }];
    expect(type).toBe('leader');
    shown.entries = itemMenu(type, ctx, { close: () => {}, glyph: () => '' })!.nodes;
}

beforeEach(() => { opened.mockReset(); shown.entries = []; openCalls.length = 0; calls.turnOff = []; calls.ask.mockReset(); calls.wake.mockReset(); calls.refresh.mockReset(); });

describe('leader ghost kebab', () => {
    it('Alpha cannot be turned off, a company agent can', () => {
        openMenu({ agentId: 1, name: 'Alpha', rank: 'alpha' });
        expect(shown.entries.map((e) => e.label)).toEqual(['leader.menu.wake', 'leader.rename.menu']);
        openMenu({ agentId: 2, name: 'Acme HQ', rank: 'company' });
        expect(shown.entries.map((e) => e.label)).toEqual(['leader.menu.wake', 'leader.rename.menu', 'leader.menu.turn_off']);
    });

    it('wake resumes the agent\'s last conversation, then re-reads the roster', async () => {
        openMenu({ agentId: 2, name: 'Acme HQ', rank: 'company' });
        shown.entries[0]!.run!(); await new Promise((r) => setTimeout(r, 0));
        expect(calls.wake).toHaveBeenCalledWith(2, 'resume');
        expect(calls.refresh).toHaveBeenCalledTimes(1);
        expect(calls.wake.mock.invocationCallOrder[0]).toBeLessThan(calls.refresh.mock.invocationCallOrder[0]!);
    });

    it('turn off sends the typed name; a cancelled modal sends nothing', async () => {
        openMenu({ agentId: 2, name: 'Acme HQ', rank: 'company' });
        const off = shown.entries[2]!;
        calls.ask.mockResolvedValueOnce(null);
        off.run!(); await new Promise((r) => setTimeout(r, 0));
        expect(calls.turnOff).toEqual([]);
        calls.ask.mockResolvedValueOnce('Acme HQ');
        off.run!(); await new Promise((r) => setTimeout(r, 0));
        expect(calls.turnOff).toEqual([[2, 'Acme HQ']]);
    });
});

describe('leader ghost row shift-click', () => {
    it('shift opens the agent terminal through openAgentTerminal; a plain click does nothing', () => {
        openGhostTerminal(new MouseEvent('click', { shiftKey: false }), { agentId: 6, name: 'Insiders', rank: 'project' });
        expect(opened).not.toHaveBeenCalled();
        openGhostTerminal(new MouseEvent('click', { shiftKey: true }), { agentId: 6, name: 'Insiders', rank: 'project' });
        expect(opened).toHaveBeenCalledWith(6);
    });
});
