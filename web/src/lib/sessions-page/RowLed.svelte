
<script lang="ts">
    import SessionFace from '../sessions/SessionFace.svelte';
    import { swarmRosterAgents } from '../../cplugs/sdk/swarm-roster.svelte';
    import { memberOf } from '../swarm-membership/member-face';
    import type { SessionListItem } from '../sessions/types';
    import type { PageRow } from './filters';

    interface Props {
        row: PageRow;
        live: SessionListItem | undefined;
        asleepUnread: boolean;
    }
    const { row, live, asleepUnread }: Props = $props();
    const asleep = $derived(row.s.state === 'asleep');
    const liveFace = $derived(live ? { ...live, agent_family: row.provider } : null);
    const member = $derived(memberOf({ ...(row.s as unknown as Record<string, unknown>), ...((live ?? {}) as Record<string, unknown>), session_uuid: row.s.session_uuid }, swarmRosterAgents()));
</script>

{#if liveFace}
    <SessionFace row={liveFace} bare {member} />
{:else}
    <SessionFace row={{ agent_family: row.provider, unread: asleepUnread }} lifecycle={asleep ? 'asleep' : undefined} bare {member} />
{/if}
