
<script lang="ts">
    import type { Attrs } from './row-plan';
    import RowChip from './RowChip.svelte';

    let { attrs }: { attrs: Attrs } = $props();
</script>

<RowChip chip={{ attrs }}><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="17" x2="12" y2="22"></line><path d="M5 17h14l-2-4V4H7v9l-2 4z"></path></svg></RowChip>
