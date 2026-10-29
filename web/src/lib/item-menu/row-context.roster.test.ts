/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { contextFromRow } from './row-context';
import { registerSwarmRoster, unregisterSwarmRoster } from '../../cplugs/sdk/swarm-roster.svelte';

const ROW = { session_uuid: 'u-7', tmux_session: 'carnivore_a', activity_status: 'idle' };

afterEach(() => unregisterSwarmRoster());

describe('contextFromRow and the Swarm roster', () => {
    test('with the plugin on, a session on the roster carries its rank', () => {
        registerSwarmRoster({ agents: () => [{ id: 7, rank: 'feature', session_uuid: 'u-7' }], refresh: async () => {} });
        expect(contextFromRow(ROW).swarmRank).toBe('feature');
    });

    test('with the plugin off, the rank is empty and nothing throws', () => {
        expect(contextFromRow(ROW).swarmRank).toBe('');
    });
});
