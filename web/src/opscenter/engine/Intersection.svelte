<script lang="ts">
  import { beginGesture } from './pointer';
  import type { SeamTrack } from './tracks';
  import type { RowId, RowModel } from './types';
  import type { LayoutStore } from './layout.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    row,
    seam,
    free,
    gutter,
    flexSpace,
    boundary,
    store,
  }: {
    store: LayoutStore;
    row: RowModel;
    seam: SeamTrack;
    free: number;
    gutter: number;
    flexSpace: number;
    boundary?: RowId;
  } = $props();

  const SIZE = 14;

  let handle = $state<HTMLElement | null>(null);
  let liftFree = 0;
  let liftFlex = 0;

  function onPointerDown(event: PointerEvent): void {
    if (!handle) return;
    const snapshot = store.snapshot();
    liftFree = free;
    liftFlex = flexSpace;
    event.stopPropagation();
    beginGesture(handle, event, {
      threshold: 2,
      coalesce: true,
      onMove: (dx, dy) =>
        boundary && boundary !== row.id
          ? store.dragCorner(snapshot, row.id, seam.index, boundary, dx, dy, liftFree, seam.leftMinPx, seam.leftMaxPx, liftFlex)
          : store.dragIntersection(
              snapshot,
              row.id,
              seam.index,
              dx,
              dy,
              liftFree,
              seam.leftMinPx,
              seam.leftMaxPx,
              liftFlex,
            ),
      onCancel: () => store.restore(snapshot),
    });
  }
</script>

<div
  bind:this={handle}
  class="oc-intersection"
  role="button"
  aria-label={t('opscenter.gutter.resize_both')}
  tabindex="-1"
  data-row={row.id}
  data-index={seam.index}
  data-boundary={boundary}
  style={`left: ${Math.round(seam.x + gutter / 2 - SIZE / 2)}px; width: ${SIZE}px`}
  onpointerdown={onPointerDown}
></div>
