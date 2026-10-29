
<script lang="ts">
    import RowChip from './RowChip.svelte';
    import type { RowChipSpec } from './row-plan';

    let { spec }: { spec: RowChipSpec } = $props();
</script>

<RowChip chip={spec} />
