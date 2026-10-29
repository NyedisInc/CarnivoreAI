/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { browserSessionsSearchHost } from './host';

type W = Record<string, unknown>;
let screen = 'launchpad';
const returned: string[] = [];

beforeEach(() => {
    screen = 'launchpad';
    returned.length = 0;
    const w = window as unknown as W;
    let bound: string | null = null;
    w.TerminalController = { term: {}, _sessionId: () => bound };
    w.API = { getSession: async (id: string) => ({ session: { id } }) };
    w.App = {
        get currentScreen() { return screen; },
        returnToExistingTerminal: async (info: { session: { id: string } }) => { bound = info.session.id; screen = 'terminal'; returned.push(bound); },
    };
});
afterEach(() => { for (const k of ['TerminalController', 'API', 'App']) delete (window as unknown as W)[k]; vi.restoreAllMocks(); });

describe('sessions-search navigate after the terminal tab is closed', () => {
    it('opens, and opens again after each close, twice over', async () => {
        const host = browserSessionsSearchHost();
        for (let round = 1; round <= 3; round += 1) {
            expect(await host.navigate('ses_a', 'carnivore_a')).toBe(true);
            expect(returned).toHaveLength(round);
            screen = 'launchpad';
        }
    });

    it('does not reconnect a terminal that is already on show', async () => {
        const host = browserSessionsSearchHost();
        await host.navigate('ses_a', 'carnivore_a');
        await host.navigate('ses_a', 'carnivore_a');
        expect(returned).toHaveLength(1);
    });
});
