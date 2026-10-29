import { afterEach, describe, expect, test, vi } from 'vitest';
import { refreshSwarmRoster, registerSwarmRoster, swarmRosterAgents, unregisterSwarmRoster } from './swarm-roster.svelte';

const AGENT = { id: 7, rank: 'feature', session_uuid: 'u-7' };

afterEach(() => unregisterSwarmRoster());

describe('with no plugin registered', () => {
    test('the roster is empty and a refresh does nothing and does not throw', async () => {
        expect(swarmRosterAgents()).toEqual([]);
        await expect(refreshSwarmRoster()).resolves.toBeUndefined();
    });
});

describe('with the plugin registered', () => {
    test('the roster is the plugin\'s and a refresh reaches the plugin', async () => {
        const refresh = vi.fn(async () => {});
        registerSwarmRoster({ agents: () => [AGENT], refresh });
        expect(swarmRosterAgents()).toEqual([AGENT]);
        await refreshSwarmRoster();
        expect(refresh).toHaveBeenCalledTimes(1);
    });

    test('after the plugin stops (unregister) the roster is empty again, and unregistering twice is harmless', async () => {
        const refresh = vi.fn(async () => {});
        registerSwarmRoster({ agents: () => [AGENT], refresh });
        unregisterSwarmRoster();
        unregisterSwarmRoster();
        expect(swarmRosterAgents()).toEqual([]);
        await refreshSwarmRoster();
        expect(refresh).not.toHaveBeenCalled();
    });
});
