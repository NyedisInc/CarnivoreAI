<script lang="ts">
  import AbsSurface from './AbsSurface.svelte';
  import CellHost from '../../CellHost.svelte';
  import type { LayoutStore } from '../layout.svelte';

  let { store, dropId }: { store: LayoutStore; dropId?: string } = $props();
</script>

<AbsSurface {store} {dropId}>
  {#snippet renderCell(slot)}
    <CellHost id={slot.id} {store} />
  {/snippet}
</AbsSurface>
