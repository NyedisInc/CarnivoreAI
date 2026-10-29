import { afterEach, describe, expect, test } from 'vitest';
import { registerSwarmRoster, unregisterSwarmRoster } from '../../cplugs/sdk/swarm-roster.svelte';
import { liveRuleContext } from './group-rule-live';

const ROW = { session_uuid: 'u-7' };

afterEach(() => unregisterSwarmRoster());

describe('isSwarm', () => {
    test('is false for every row while no plugin registered a roster', () => {
        expect(liveRuleContext.isSwarm(ROW)).toBe(false);
    });

    test('is true for a row bound to a registered roster agent, and false again after the plugin stops', () => {
        registerSwarmRoster({ agents: () => [{ id: 7, rank: 'feature', session_uuid: 'u-7' }], refresh: async () => {} });
        expect(liveRuleContext.isSwarm(ROW)).toBe(true);
        expect(liveRuleContext.isSwarm({ session_uuid: 'u-other' })).toBe(false);
        unregisterSwarmRoster();
        expect(liveRuleContext.isSwarm(ROW)).toBe(false);
    });
});
