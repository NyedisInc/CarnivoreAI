
<script lang="ts">
    import BandSection from './BandSection.svelte';
    import BrowserRow from './BrowserRow.svelte';
    import LayoutRow from './LayoutRow.svelte';
    import SessionRow from './SessionRow.svelte';
    import SidebarRow from './SidebarRow.svelte';
    import SleepFoldRow from './SleepFoldRow.svelte';
    import type { RowPlan } from './row-plan';

    let { r }: { r: RowPlan } = $props();
</script>

{#if r.type === 'session'}<SessionRow p={r} />{:else if r.type === 'browser'}<BrowserRow p={r} />{:else}<LayoutRow p={r} />{#if r.members}<div class="session-sidebar-group__body session-sidebar-layout__members" id={r.members.bodyId} data-layout-members={r.members.uuid} style={r.parts.attrs.style}>{#each r.members.groups ?? [] as g (g.key)}<BandSection s={g} />{/each}{#each r.members.rows as m (m.key)}<SidebarRow r={m} />{/each}{#if r.members.sleepingRows?.length}<SleepFoldRow bandKey={r.key} rows={r.members.sleepingRows} />{/if}</div>{/if}{/if}
