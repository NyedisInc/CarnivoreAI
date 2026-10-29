
<script lang="ts">
    import BrowserRow from './BrowserRow.svelte';
    import SessionRow from './SessionRow.svelte';
    import SidebarRow from './SidebarRow.svelte';
    import type { RowPlan } from './row-plan';

    let { r }: { r: RowPlan } = $props();
</script>

{#if r.type === 'session'}<SessionRow p={r} />{:else if r.type === 'browser'}<BrowserRow p={r} />{:else}{@html r.html}{#if r.members}<div class="session-sidebar-group__body session-sidebar-layout__members" id={r.members.bodyId} data-layout-members={r.members.uuid}>{#each r.members.rows as m (m.key)}<SidebarRow r={m} />{/each}</div>{/if}{/if}
