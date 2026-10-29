<script lang="ts">
  import type { Component } from 'svelte';
  import CellFrame from '../CellFrame.svelte';
  import { META, metaFor } from '../../engine/meta';
  import { homeLayout } from '../../engine/layout.svelte';
  import type { SlotId } from '../../engine/types';
  import type { CellProps } from '../../lib/cell';

  let { slot, cell, width = 800, height = 400 }: { slot: SlotId; cell: Component<CellProps>; width?: number; height?: number } = $props();
  const meta = $derived(metaFor(slot, META));
  const Cell = $derived(cell);
</script>
<CellFrame {meta} instance={slot} widthState="wide" heightState="pane" store={homeLayout}>
  {#snippet body()}
    <Cell {width} {height} {meta} instance={slot} />
  {/snippet}
</CellFrame>
