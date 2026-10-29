
<script lang="ts">
    import type { Attrs } from './row-plan';
    import RowChip from './RowChip.svelte';
    import { PIN_SVG } from './row-chips';

    let { attrs }: { attrs: Attrs } = $props();
</script>

<RowChip chip={{ attrs, svg: PIN_SVG }} />
