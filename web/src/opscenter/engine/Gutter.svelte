<script lang="ts">
  /*  hidden  */
  import { beginGesture } from './pointer';
  import { META, metaFor } from './meta';
  import { ROW_MAX, rowFloor } from './model';
  import { ROW_MIN } from './floors';
  import type { SeamTrack } from './tracks';
  import type { Layout, RowModel } from './types';
  import type { LayoutStore } from './layout.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    axis,
    row,
    seam,
    free = 0,
    flexSpace = 0,
    gutter,
    belowLabel = '',
    mirror = false,
    store,
  }: {
    store: LayoutStore;
    axis: 'x' | 'y';
    row: RowModel;
    seam?: SeamTrack;
    free?: number;
    flexSpace?: number;
    gutter: number;
    belowLabel?: string;
    mirror?: boolean;
  } = $props();

  const STEP = 0.02;
  const BIG_STEP = 0.08;
  const THRESHOLD = 2;

  let handle = $state<HTMLElement | null>(null);
  let snapshot: Layout | null = null;
  let liftFree = 0;
  let liftFlex = 0;

  const index = $derived(seam?.index ?? 0);
  const left = $derived(axis === 'x' ? row.slots[index] : undefined);
  const right = $derived(axis === 'x' ? row.slots[index + 1] : undefined);

  const below = $derived.by(() => {
    if (axis !== 'y') return undefined;
    const rows = store.state.layout.rows;
    const at = rows.findIndex((entry) => entry.id === row.id);
    return at >= 0 ? rows[at + 1] : undefined;
  });

  const label = $derived.by(() => {
    if (axis === 'x') {
      const a = left ? t(metaFor(left.id, META).titleKey) : t('opscenter.gutter.panel');
      const b = right ? t(metaFor(right.id, META).titleKey) : t('opscenter.gutter.panel');
      return t('opscenter.gutter.resize', { first: a, second: b });
    }
    const a = row.slots[0] ? t(metaFor(row.slots[0].id, META).titleKey) : t('opscenter.gutter.row');
    return t('opscenter.gutter.resize', {
      first: a,
      second: belowLabel || t('opscenter.gutter.row_below'),
    });
  });

  const value = $derived.by(() => {
    if (axis === 'x') {
      if (!seam || seam.pairPx <= 0) return { now: 50, min: 0, max: 100 };
      const pair = seam.pairPx;
      return {
        now: Math.round((seam.leftPx / pair) * 100),
        min: Math.round(Math.min(seam.leftMinPx / pair, 1) * 100),
        max: Math.round(Math.max(0, Math.min(seam.leftMaxPx / pair, 1)) * 100),
      };
    }
    if (row.kind === 'px') return { now: Math.round(row.size), min: rowFloor(row, META), max: ROW_MAX };
    if (!below) return { now: 50, min: 0, max: 100 };
    const pair = row.size + below.size;
    if (pair <= 0) return { now: 50, min: 0, max: 100 };
    const floor = ROW_MIN / Math.max(1, flexSpace);
    return {
      now: Math.round((row.size / pair) * 100),
      min: Math.round(Math.min(floor / pair, 1) * 100),
      max: Math.round(Math.max(0, (pair - floor) / pair) * 100),
    };
  });

  const spoken = $derived(
    axis === 'y' && row.kind === 'px'
      ? t('opscenter.gutter.at_pixels', { label, pixels: value.now })
      : t('opscenter.gutter.at_percent', { label, percent: value.now }),
  );

  function applyDelta(dx: number, dy: number): void {
    if (!snapshot) return;
    if (axis === 'x') {
      if (!seam) return;
      store.dragColumns(snapshot, row.id, seam.index, dx, liftFree, seam.leftMinPx, seam.leftMaxPx);
    } else store.dragRows(snapshot, row.id, dy, liftFlex);
  }

  function light(state: 'hover' | 'active' | null): void {
    if (!handle || axis !== 'x') return;
    const same = (handle.getRootNode() as Document | ShadowRoot).querySelectorAll<HTMLElement>(`.oc-gutter-col[data-index="${index}"]`);
    for (const piece of same) {
      if (piece.dataset['row'] !== row.id) continue;
      if (state) piece.setAttribute('data-lit', state);
      else piece.removeAttribute('data-lit');
    }
  }

  function settle(): void {
    light(handle?.matches(':hover') ? 'hover' : null);
  }

  function onPointerDown(event: PointerEvent): void {
    if (!handle) return;
    light('active');
    snapshot = store.snapshot();
    liftFree = seam ? seam.space : free;
    liftFlex = flexSpace;
    const held = snapshot;
    beginGesture(handle, event, {
      threshold: THRESHOLD,
      coalesce: true,
      onMove: (dx, dy) => applyDelta(dx, dy),
      onCancel: () => {
        store.restore(held);
        settle();
      },
      onEnd: (lifted) => {
        settle();
        if (lifted) store.announceLater(spoken);
      },
    });
  }

  function step(pixels: number): void {
    const base = store.snapshot();
    if (axis === 'x') {
      if (!seam) return;
      store.dragColumns(base, row.id, seam.index, pixels, seam.space, seam.leftMinPx, seam.leftMaxPx);
    } else store.dragRows(base, row.id, pixels, flexSpace);
    store.announceLater(spoken);
  }

  function reset(): void {
    if (axis === 'x') store.resetOneRow(row.id);
    else store.resetRowHeights();
    store.announceLater(t('opscenter.gutter.reset', { label }));
  }

  function onKeyDown(event: KeyboardEvent): void {
    const budget = axis === 'x' ? free : row.kind === 'px' ? row.size : flexSpace;
    const amount = (event.shiftKey ? BIG_STEP : STEP) * Math.max(1, budget);
    const back = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
    const forward = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
    if (event.key === back) {
      event.preventDefault();
      step(-amount);
    } else if (event.key === forward) {
      event.preventDefault();
      step(amount);
    } else if (event.key === 'Home') {
      event.preventDefault();
      step(-Math.max(1, budget));
    } else if (event.key === 'End') {
      event.preventDefault();
      step(Math.max(1, budget));
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      reset();
    }
  }

  function onDoubleClick(): void {
    if (snapshot) store.restore(snapshot);
    reset();
  }
</script>


<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div
  bind:this={handle}
  class="oc-gutter"
  class:oc-gutter-col={axis === 'x'}
  class:oc-gutter-row={axis === 'y'}
  role="separator"
  aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'}
  aria-label={mirror ? undefined : label}
  aria-hidden={mirror ? 'true' : undefined}
  aria-valuenow={value.now}
  aria-valuemin={value.min}
  aria-valuemax={value.max}
  tabindex={mirror ? -1 : 0}
  data-mirror={mirror ? '' : undefined}
  data-row={row.id}
  data-index={axis === 'x' ? index : undefined}
  data-boundary={axis === 'y' ? row.id : undefined}
  onpointerdown={onPointerDown}
  onkeydown={onKeyDown}
  ondblclick={onDoubleClick}
  onpointerenter={() => {
    if (handle?.getAttribute('data-lit') !== 'active') light('hover');
  }}
  onpointerleave={() => {
    if (handle?.getAttribute('data-lit') !== 'active') light(null);
  }}
  onfocus={() => light('active')}
  onblur={() => light(null)}
></div>
