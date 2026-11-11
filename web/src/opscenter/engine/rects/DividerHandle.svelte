<script lang="ts">
  import type { LayoutStore } from '../layout.svelte';
  import { META, metaFor } from '../meta';
  import { ROW_MAX, rowFloor } from '../model';
  import { ROW_MIN } from '../floors';
  import { t } from '../../../lib/i18n/index.svelte';
  import { applyDivider, type DividerSpec } from './dividers';

  let { spec, store }: { spec: DividerSpec; store: LayoutStore } = $props();

  const STEP = 0.02;
  const BIG_STEP = 0.08;

  const row = $derived(store.state.layout.rows.find((one) => one.id === spec.rowId));
  const below = $derived.by(() => {
    const rows = store.state.layout.rows;
    const at = rows.findIndex((one) => one.id === spec.rowId);
    return at >= 0 ? rows[at + 1] : undefined;
  });
  const axis = $derived(spec.kind === 'col' ? 'x' : 'y');
  const square = $derived(spec.kind === 'inter' || spec.kind === 'corner');

  function titleOf(id: string | undefined, fallback: string): string {
    return id ? t(metaFor(id as never, META).titleKey) : fallback;
  }

  const label = $derived.by(() => {
    if (square) return t('opscenter.gutter.resize_both');
    if (spec.kind === 'col') {
      const at = spec.seam?.index ?? 0;
      return t('opscenter.gutter.resize', {
        first: titleOf(row?.slots[at]?.id, t('opscenter.gutter.panel')),
        second: titleOf(row?.slots[at + 1]?.id, t('opscenter.gutter.panel')),
      });
    }
    const first = titleOf(row?.slots[0]?.id, t('opscenter.gutter.row'));
    if (spec.kind === 'tail') return t('opscenter.gutter.grow_down', { label: first });
    return t('opscenter.gutter.resize', { first, second: titleOf(below?.slots[0]?.id, t('opscenter.gutter.row_below')) });
  });

  const value = $derived.by(() => {
    if (spec.kind === 'col') {
      const seam = spec.seam;
      if (!seam || seam.pairPx <= 0) return { now: 50, min: 0, max: 100 };
      return {
        now: Math.round((seam.leftPx / seam.pairPx) * 100),
        min: Math.round(Math.min(seam.leftMinPx / seam.pairPx, 1) * 100),
        max: Math.round(Math.max(0, Math.min(seam.leftMaxPx / seam.pairPx, 1)) * 100),
      };
    }
    if (!row) return { now: 50, min: 0, max: 100 };
    if (row.kind === 'px') return { now: Math.round(row.size), min: rowFloor(row, META), max: ROW_MAX };
    if (!below) return { now: 50, min: 0, max: 100 };
    const pair = row.size + below.size;
    if (pair <= 0) return { now: 50, min: 0, max: 100 };
    const floor = ROW_MIN / Math.max(1, spec.flexSpace);
    return {
      now: Math.round((row.size / pair) * 100),
      min: Math.round(Math.min(floor / pair, 1) * 100),
      max: Math.round(Math.max(0, (pair - floor) / pair) * 100),
    };
  });

  const spoken = $derived(
    axis === 'y' && row?.kind === 'px'
      ? t('opscenter.gutter.at_pixels', { label, pixels: value.now })
      : t('opscenter.gutter.at_percent', { label, percent: value.now }),
  );

  function step(pixels: number): void {
    const base = store.snapshot();
    const next = applyDivider(base, spec, axis === 'x' ? pixels : 0, axis === 'y' ? pixels : 0);
    if (next !== base) store.commitLayout(next, base);
    store.announceLater(spoken);
  }

  let gutter = $state<HTMLElement | null>(null);

  function light(state: 'hover' | 'active' | null): void {
    if (!gutter || axis !== 'x') return;
    const root = gutter.getRootNode() as Document | ShadowRoot;
    for (const piece of root.querySelectorAll<HTMLElement>(`.oc-gutter-col[data-index="${spec.seam?.index}"]`)) {
      if (piece.dataset['row'] !== spec.rowId) continue;
      if (state) piece.setAttribute('data-lit', state);
      else piece.removeAttribute('data-lit');
    }
  }

  function settle(): void {
    light(gutter?.matches(':hover') ? 'hover' : null);
  }

  function onPointerDown(): void {
    light('active');
    const end = (): void => {
      window.removeEventListener('pointerup', end, true);
      window.removeEventListener('pointercancel', end, true);
      settle();
    };
    window.addEventListener('pointerup', end, true);
    window.addEventListener('pointercancel', end, true);
  }

  function reset(): void {
    if (axis === 'x') store.resetOneRow(spec.rowId);
    else store.resetRowHeights();
    store.announceLater(t('opscenter.gutter.reset', { label }));
  }

  function onKeyDown(event: KeyboardEvent): void {
    const budget = axis === 'x' ? spec.rowFree : row?.kind === 'px' ? (row?.size ?? 1) : spec.flexSpace;
    const amount = (event.shiftKey ? BIG_STEP : STEP) * Math.max(1, budget);
    const back = axis === 'x' ? 'ArrowLeft' : 'ArrowUp';
    const forward = axis === 'x' ? 'ArrowRight' : 'ArrowDown';
    if (event.key === back) step(-amount);
    else if (event.key === forward) step(amount);
    else if (event.key === 'Home') step(-Math.max(1, budget));
    else if (event.key === 'End') step(Math.max(1, budget));
    else if (event.key === 'Enter' || event.key === ' ') reset();
    else return;
    event.preventDefault();
  }
</script>

<div
  class="abs-handle"
  data-square={square ? "" : undefined}
  data-abs-divider={spec.id}
  style={`left: ${spec.rect.x}px; top: ${spec.rect.y}px; width: ${spec.rect.w}px; height: ${spec.rect.h}px`}
>
  {#if square}
    <div class="oc-intersection" role="button" aria-label={label} tabindex="-1" data-row={spec.rowId} data-diag={spec.diag}></div>
  {:else}
    
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div
      class={`oc-gutter ${axis === 'x' ? 'oc-gutter-col' : 'oc-gutter-row'}`}
      role="separator"
      aria-orientation={axis === 'x' ? 'vertical' : 'horizontal'}
      aria-label={spec.mirror ? undefined : label}
      aria-hidden={spec.mirror ? 'true' : undefined}
      aria-valuenow={value.now}
      aria-valuemin={value.min}
      aria-valuemax={value.max}
      tabindex={spec.mirror ? -1 : 0}
      bind:this={gutter}
      data-row={spec.rowId}
      data-index={axis === 'x' ? spec.seam?.index : undefined}
      data-boundary={axis === 'y' ? spec.rowId : undefined}
      onkeydown={onKeyDown}
      ondblclick={reset}
      onpointerdown={onPointerDown}
      onpointerenter={() => {
        if (gutter?.getAttribute('data-lit') !== 'active') light('hover');
      }}
      onpointerleave={() => {
        if (gutter?.getAttribute('data-lit') !== 'active') light(null);
      }}
      onfocus={() => light('active')}
      onblur={() => light(null)}
    ></div>
  {/if}
</div>

<style>
  @layer components {
    .abs-handle {
      position: absolute;
      z-index: 3;
      touch-action: none;
    }

    .abs-handle[data-square] {
      z-index: 4;
    }

    .abs-handle > :global(.oc-gutter),
    .abs-handle > :global(.oc-intersection) {
      position: absolute;
      inset: 0;
      width: auto;
      height: auto;
      transform: none;
    }
  }
</style>
