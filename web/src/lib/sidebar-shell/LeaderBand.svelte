
<script lang="ts">
    import Band from './Band.svelte';
    import SidebarRow from './SidebarRow.svelte';
    import { bandEvents } from './row-events';
    import type { RowPlan } from './row-plan';

    let { row }: { row: RowPlan } = $props();
</script>

<Band kind="session-sidebar-leader" attrs={{ 'data-group': 'leader' }} gestures={bandEvents()}><SidebarRow r={row} /></Band>
