import { swarmRoster, startSwarmRoster } from '../../cplugs/huddle/agents/agent-roster.svelte';
import { projects } from '../../opscenter/api/projects.svelte';
import { indexLeaders, type LeaderIndex, type RosterWithCompany } from './leaders';
import { repaintDrawerRows } from './interaction-globals';

export function leaderIndex(): LeaderIndex {
    return indexLeaders(swarmRoster.agents);
}

export function leaderRoster(): readonly RosterWithCompany[] {
    return swarmRoster.agents;
}

export function projectNameOf(id: number): string | null {
    const hit = (projects.data ?? []).find((p) => p.id === id);
    return hit && typeof hit.name === 'string' ? hit.name : null;
}

let stopWatching: (() => void) | null = null;

export function watchLeaders(): void {
    if (stopWatching) return;
    const stopRoster = startSwarmRoster();
    let first = true;
    const stopEffect = $effect.root(() => {
        const signature = $derived(JSON.stringify(swarmRoster.agents
            .filter((a) => a.rank === 'alpha' || a.rank === 'company' || a.rank === 'project')
            .map((a) => [a.id, a.rank, a.display_name, a.session_row_id ?? null, a.session_uuid ?? null, a.company_id ?? null, a.project_id ?? null, a.state ?? null])));
        const spawnedSignature = $derived(JSON.stringify(swarmRoster.agents
            .filter((a) => a.rank === 'task' || a.rank === 'feature' || a.rank === 'project')
            .map((a) => [a.id, a.rank, a.parent_id ?? null, a.session_row_id ?? null, a.session_uuid ?? null])));
        $effect(() => {
            void signature;
            void spawnedSignature;
            if (first) { first = false; return; }
            repaintDrawerRows();
        });
    });
    stopWatching = () => { stopEffect(); stopRoster(); };
}
