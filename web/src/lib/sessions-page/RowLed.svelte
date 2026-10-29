
<script lang="ts">
    import SessionFace from '../sessions/SessionFace.svelte';
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
</script>

{#if liveFace}
    <SessionFace row={liveFace} bare />
{:else}
    <SessionFace row={{ agent_family: row.provider, unread: asleepUnread }} lifecycle={asleep ? 'asleep' : undefined} bare />
{/if}
