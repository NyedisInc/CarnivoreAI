<script lang="ts">
  import type { Snippet } from 'svelte';
  import Gutter from './Gutter.svelte';
  import type { RowModel, Slot, SlotId } from './types';
  import type { RowTracks } from './tracks';
  import type { LayoutStore } from './layout.svelte';
  import { viewport } from './viewport.svelte';
  import { META, phoneOrderOf } from './meta';
  import { layoutZoom } from './layout-zoom.svelte';

  let {
    row,
    tracks,
    spanHeight,
    gutter,
    cell,
    store,
  }: {
    row: RowModel;
    tracks: RowTracks;
    spanHeight: ReadonlyMap<SlotId, number>;
    gutter: number;
    cell: Snippet<[Slot, number]>;
    store: LayoutStore;
  } = $props();

  const dragState = $derived(store.drag);

  function seamAfter(at: number) {
    return tracks.seams.find((one) => one.afterVisual === at);
  }

  function stackEdge(id: SlotId | null): 'above' | 'below' | null {
    const target = dragState.target;
    if (!id || !target || target.kind !== 'stack' || target.of !== id) return null;
    return target.edge;
  }

  const insertAt = $derived.by(() => {
    const target = dragState.target;
    if (!target || target.kind !== 'row' || target.row !== row.id) return -1;
    const index = Math.min(Math.max(target.index, 0), tracks.cells.length);
    const held = tracks.cells[index];
    if (held) return Math.max(0, held.x - gutter / 2);
    const last = tracks.cells[tracks.cells.length - 1];
    return last ? Math.max(0, last.x + last.width) : 0;
  });
</script>

<div class="oc-row" data-row={row.id} style={`--tracks: ${tracks.template}`}>
  {#each tracks.cells as drawn, at (drawn.slotId ?? `reserved-${at}`)}
    {#if drawn.slotId === null}
      
      <div class="oc-cellslot oc-cellslot-reserved" aria-hidden="true"></div>
    {:else}
      <!-- position:
           fixed -->
      <div
        class="oc-cellslot"
        class:oc-slot-lifted={dragState.id === drawn.slotId}
        class:oc-cellslot-span={drawn.span >= 2}
        class:oc-stack-above={stackEdge(drawn.slotId) === 'above'}
        class:oc-stack-below={stackEdge(drawn.slotId) === 'below'}
        class:oc-cellslot-zoomed={layoutZoom.isZoomed(drawn.slotId)}
        data-slot={drawn.slotId}
        style={`--oc-phone-order: ${phoneOrderOf(drawn.slotId, drawn.index, META)}; grid-column: ${at * 2 + 1}${
          drawn.span >= 2 ? `; --oc-span-h: ${spanHeight.get(drawn.slotId) ?? 0}px` : ''
        }${
          dragState.id === drawn.slotId ? `; --oc-lift-x: ${dragState.dx}px; --oc-lift-y: ${dragState.dy}px` : ''
        }`}
      >
        {#if row.slots[drawn.index]}
          {@render cell(row.slots[drawn.index]!, drawn.index)}
        {/if}
      </div>
    {/if}
    {#if at < tracks.cells.length - 1}
      {#if viewport.wide && seamAfter(at)}
        <Gutter axis="x" {row} seam={seamAfter(at)!} free={tracks.free} {gutter} {store} />
      {:else if viewport.wide}
        
        <div class="oc-gutter oc-gutter-inert" aria-hidden="true"></div>
      {/if}
    {/if}
  {/each}
  {#if insertAt >= 0}
    <div class="oc-insert" style={`left: ${Math.round(insertAt)}px`} aria-hidden="true"></div>
  {/if}
</div>
