import { isKeptAwake } from '../auto-sleep/auto-sleep-store.svelte';
import { swarmRosterAgents } from '../../cplugs/sdk/swarm-roster.svelte';
import { memberOf } from '../swarm-membership/member-face';
import { isPinned } from './store';
import type { RuleContext } from './group-rule';

export const liveRuleContext: RuleContext = {
    keptAwake: (name) => isKeptAwake(name) === true,
    isPinned: (name) => isPinned(name),
    isSwarm: (row) => memberOf(row, swarmRosterAgents()) !== null,
};
