
<script lang="ts">
    import RowChip from './RowChip.svelte';
    import type { RowChipSpec } from './row-plan';

    let { actions }: { actions: RowChipSpec[] } = $props();
</script>

{#each actions as action, i (i)}<RowChip chip={action} />{/each}
