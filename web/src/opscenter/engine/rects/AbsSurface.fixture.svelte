<script lang="ts">
  import AbsSurface from './AbsSurface.svelte';
  import type { LayoutStore } from '../layout.svelte';

  let { store, dropId }: { store: LayoutStore; dropId?: string } = $props();
</script>

<AbsSurface {store} {dropId}>
  {#snippet renderCell(slot)}
    <div data-cell-body={slot.id}>{slot.id}</div>
  {/snippet}
</AbsSurface>
