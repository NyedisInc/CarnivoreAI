<script lang="ts">
  import type { Snippet } from 'svelte';
  import GridRow from './GridRow.svelte';
  import Gutter from './Gutter.svelte';
  import Intersection from './Intersection.svelte';
  import type { RowModel, Slot } from './types';
  import type { LayoutStore } from './layout.svelte';
  import { META, metaFor } from './meta';
  import { GUTTER, computeTracks } from './tracks';
  import { boundaryHandles } from './row-handles';
  import { edgeBox, spanCorners, spanEdges } from './span-edges';
  import { observeCell, sizeOf, surfaceKeyOf } from './observe.svelte';
  import { viewport } from './viewport.svelte';
  import { layoutZoom } from './layout-zoom.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    gutter = GUTTER,
    renderCell,
    store,
    sizeKey: sizeKeyOverride,
  }: {
    gutter?: number;
    sizeKey?: string;
    renderCell: Snippet<[Slot, RowModel, number]>;
    store: LayoutStore;
  } = $props();

  const rows = $derived(store.state.layout.rows);
  const sizeKey = $derived(sizeKeyOverride ?? surfaceKeyOf(store.page));
  const surface = $derived(sizeOf(sizeKey));

  //  hidden 
  $effect(() => {
    if (store.page !== 'terminal') return;
    const zoomed = layoutZoom.zoomed;
    if (zoomed === null) return;
    if (rows.some((row) => row.slots.some((slot) => slot.id === zoomed))) return;
    layoutZoom.forget(zoomed);
  });

  const tracks = $derived(
    computeTracks({ rows, width: surface.width, height: surface.height, gutter, metas: META }),
  );

  const measured = $derived(store.page === 'home' || (surface.width > 0 && surface.height > 0));

  function crossed(at: number): [number, number][] {
    const under = tracks.rows[at + 1];
    if (!under) return [];
    return under.cells
      .filter((cell) => cell.reserved)
      .map((cell) => [cell.x, cell.x + cell.width] as [number, number]);
  }

  function handlesUnder(at: number): [number, number][] {
    return boundaryHandles(tracks, at, surface.width, gutter);
  }

  const rowIds = $derived(rows.map((row) => row.id));

  const edges = $derived(spanEdges(tracks, rowIds));
  const corners = $derived(spanCorners(tracks, rowIds, edges));

  function isSpanEdge(at: number, afterVisual: number): boolean {
    return edges.some((edge) => edge.rowAt === at && edge.seam.afterVisual === afterVisual);
  }

  function seamClear(at: number, x: number): boolean {
    return !crossed(at).some(([start, end]) => x >= start && x <= end);
  }

  function movable(at: number): boolean {
    return at < rows.length - 1;
  }

  function rowLabel(row: RowModel | undefined): string {
    const first = row?.slots[0];
    if (!first) return t('opscenter.gutter.row_below');
    const meta = metaFor(first.id, META);
    return meta.titleName ?? t(meta.titleKey);
  }

  const newRowAt = $derived.by(() => {
    const target = store.drag.target;
    if (!target || target.kind !== 'new') return -1;
    if (target.after === null) return 0;
    const at = rows.findIndex((row) => row.id === target.after);
    const held = tracks.rows[at];
    return held ? held.top + held.height + gutter / 2 : -1;
  });

  const newColumnAt = $derived.by(() => {
    const target = store.drag.target;
    if (!target || target.kind !== 'column') return null;
    const at = rows.findIndex((row) => row.id === target.row);
    const home = tracks.rows[at];
    const last = tracks.rows[at + target.rows - 1];
    const pointed = tracks.rows[rows.findIndex((row) => row.id === target.at)];
    if (!home || !last || !pointed) return null;
    const index = Math.min(Math.max(target.index, 0), pointed.cells.length);
    const held = pointed.cells[index];
    const end = pointed.cells[pointed.cells.length - 1];
    const x = held ? held.x - gutter / 2 : end ? end.x + end.width : 0;
    return { left: Math.max(0, x), top: home.top, height: last.top + last.height - home.top };
  });
</script>

<div
  class="oc-surface"
  class:oc-surface-zoomable={store.page === 'terminal'}
  style={measured ? `--rows: ${tracks.template}; --oc-surface-h: ${tracks.contentHeight}px` : '--rows: none'}
  {@attach observeCell(sizeKey)}
>
  {#each measured ? rows : [] as row, index (row.id)}
    <GridRow
      {row}
      tracks={tracks.rows[index]!}
      spanHeight={tracks.spanHeight}
      {gutter}
      {store}
    >
      {#snippet cell(slot, slotIndex)}
        {@render renderCell(slot, row, slotIndex)}
      {/snippet}
    </GridRow>
    {#if index < rows.length - 1 && viewport.wide}
      <div class="oc-gutter-band">
        {#if movable(index) && handlesUnder(index).length}
          {#each handlesUnder(index) as band (band[0])}
            <div class="oc-gutter-slice" style={`left: ${band[0]}px; width: ${band[1]}px`}>
              <Gutter
                axis="y"
                {row}
                {gutter}
                flexSpace={tracks.flexSpace}
                belowLabel={rowLabel(rows[index + 1])}
                {store}
              />
            </div>
          {/each}
          {#each (tracks.rows[index]?.seams ?? []).filter((seam) => seamClear(index, seam.x) && !isSpanEdge(index, seam.afterVisual)) as seam (seam.index)}
            <Intersection
              {row}
              {seam}
              free={tracks.rows[index]?.free ?? 1}
              {gutter}
              flexSpace={tracks.flexSpace}
              {store}
            />
          {/each}
        {/if}
        {#each corners.filter((corner) => corner.bandAt === index) as corner (`${corner.seamRow}-${corner.seam.index}-${corner.boundaryRow}`)}
          <Intersection
            row={rows.find((one) => one.id === corner.seamRow)!}
            seam={corner.seam}
            free={tracks.rows[rows.findIndex((one) => one.id === corner.seamRow)]?.free ?? 1}
            {gutter}
            flexSpace={tracks.flexSpace}
            boundary={corner.boundaryRow}
            {store}
          />
        {/each}
      </div>
    {/if}
  {/each}
  {#if viewport.wide}
    {#each measured ? edges : [] as edge (`${edge.rowId}-${edge.seam.index}`)}
      {@const box = edgeBox(tracks, edge)}
      <div
        class="oc-span-edge"
        data-span-edge={edge.rowId}
        style={`left: ${Math.round(edge.seam.x)}px; top: ${Math.round(box.top)}px; width: ${gutter}px; height: ${Math.round(box.height)}px`}
      >
        <Gutter
          axis="x"
          row={rows[edge.rowAt]!}
          seam={edge.seam}
          free={tracks.rows[edge.rowAt]?.free ?? 1}
          {gutter}
          mirror
          {store}
        />
      </div>
    {/each}
  {/if}
  {#if newColumnAt}
    <div
      class="oc-insert-column"
      style={`left: ${Math.round(newColumnAt.left)}px; top: ${Math.round(newColumnAt.top)}px; height: ${Math.round(newColumnAt.height)}px`}
      aria-hidden="true"
    ></div>
  {/if}
  {#if newRowAt >= 0}
    <div class="oc-insert-row" style={`top: ${Math.round(newRowAt)}px`} aria-hidden="true"></div>
  {/if}
</div>
