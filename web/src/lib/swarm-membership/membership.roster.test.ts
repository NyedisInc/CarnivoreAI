/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

vi.mock('../../opscenter/api/auth.svelte', () => ({ authFetch: vi.fn(async () => ({})) }));
vi.mock('../confirm-ok/confirm-ok', () => ({ confirmOk: vi.fn(async () => true) }));
vi.mock('../sidebar-shell/interaction-globals', () => ({ announceFailure: vi.fn() }));

import { joinSwarm } from './membership';
import { registerSwarmRoster, unregisterSwarmRoster } from '../../cplugs/sdk/swarm-roster.svelte';

afterEach(() => unregisterSwarmRoster());

describe('joinSwarm and the roster', () => {
    test('a join asks the registered roster reader to re-read', async () => {
        const refresh = vi.fn(async () => {});
        registerSwarmRoster({ agents: () => [], refresh });
        expect(await joinSwarm('u-1')).toBe(true);
        expect(refresh).toHaveBeenCalledTimes(1);
    });

    test('with the plugin off, a join still completes and nothing throws', async () => {
        expect(await joinSwarm('u-1')).toBe(true);
    });
});
