
<script lang="ts">
    import EndedSessionRow from './EndedSessionRow.svelte';
    import ProjectSessionRow from './ProjectSessionRow.svelte';
    import { rowKey, type TreeSessionRow } from './project-groups';
    import type { ProjectTreeHost } from './project-tree-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        sessions: TreeSessionRow[];
        workStamps: Map<string, string>;
        transports?: Map<string, string>;
        host: ProjectTreeHost;
        t?: Translate;
    }

    let {
        sessions,
        workStamps,
        transports = new Map<string, string>(),
        host,
        t,
    }: Props = $props();
</script>

{#each sessions as row (rowKey(row))}
    {#if row.ended}
        <EndedSessionRow {row} {host} {t} />
    {:else}
        <ProjectSessionRow
            {row}
            workStamp={workStamps.get(row.name) ?? null}
            transport={transports.get(row.name) ?? null}
            {host}
            {t}
        />
    {/if}
{/each}
