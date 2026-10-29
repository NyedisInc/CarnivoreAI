
<script lang="ts">
  import { tick } from 'svelte';
  import { legendFitsOneRow, legendPages, type LegendItem } from './legend-pages';
  import { t } from '../../../lib/i18n/index.svelte';

  let { items, onToggle, wrap = false }: { items: LegendItem[]; onToggle: (name: string) => void; wrap?: boolean } = $props();

  let box = $state<HTMLElement | null>(null);
  let track = $state<HTMLElement | null>(null);
  let pagerProbe = $state<HTMLElement | null>(null);
  let boxPx = $state(0);
  let pagerPx = $state(0);
  let widths = $state<number[]>([]);
  let gapPx = $state(0);
  let page = $state(0);

  const paged = $derived(!wrap && widths.length > 0 && !legendFitsOneRow(widths, boxPx, gapPx));
  const room = $derived(paged ? Math.max(0, boxPx - pagerPx) : boxPx);
  const starts = $derived(paged ? legendPages(widths, room, gapPx) : [0]);
  const at = $derived(Math.min(page, Math.max(0, starts.length - 1)));
  const first = $derived(starts[at] ?? 0);
  const last = $derived((starts[at + 1] ?? items.length) - 1);
  const shift = $derived(widths.slice(0, first).reduce((sum, width) => sum + width + gapPx, 0));

  const cap = $derived(boxPx > 0 ? (wrap || items.length === 1 ? boxPx : Math.max(0, boxPx - pagerPx)) : null);

  $effect(() => {
    if (!box || !track) return;
    const row = box;
    const list = track;
    void items;
    void cap;
    const measure = async (): Promise<void> => {
      boxPx = row.clientWidth;
      pagerPx = pagerProbe?.offsetWidth ?? 0;
      gapPx = parseFloat(getComputedStyle(list).columnGap) || 0;
      await tick();
      widths = [...list.children].map((child) => (child as HTMLElement).offsetWidth);
    };
    void measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => { void measure(); });
    observer.observe(row);
    return () => observer.disconnect();
  });
</script>

{#if items.length}
  <div bind:this={box} class="chart-legend">
    <div class="chart-legend__view">
      <ul bind:this={track} class="chart-legend__track" class:chart-legend__track--wrap={wrap} style:transform={`translateX(-${shift}px)`} style:--legend-cap={cap === null ? null : `${cap}px`}>
        {#each items as item, index (item.id ?? index)}
          <li class="chart-legend__cell" class:chart-legend__cell--off={index < first || index > last}>
            <button type="button" class="chart-legend__item" class:chart-legend__item--dim={!item.on} aria-pressed={item.on} tabindex={index < first || index > last ? -1 : 0}
              title={item.name} onclick={() => onToggle(item.name)}>
              <i class="chart-legend__swatch" style:background={item.color} aria-hidden="true"></i><span>{item.name}</span>
            </button>
          </li>
        {/each}
      </ul>
    </div>
    {#if paged}
      <div class="chart-legend__pager">
        <button type="button" class="chart-legend__step" disabled={at === 0} aria-label={t('analytics.legend_previous')} onclick={() => { page = at - 1; }}>&#9664;</button>
        <span>{at + 1}/{starts.length}</span>
        <button type="button" class="chart-legend__step" disabled={at >= starts.length - 1} aria-label={t('analytics.legend_next')} onclick={() => { page = at + 1; }}>&#9654;</button>
      </div>
    {/if}
    <div bind:this={pagerProbe} class="chart-legend__pager chart-legend__pager--probe" aria-hidden="true"><span class="chart-legend__step">&#9664;</span><span>99/99</span><span class="chart-legend__step">&#9654;</span></div>
  </div>
{/if}

<style>
  @layer components {
    .chart-legend { position: relative; display: flex; flex: none; align-items: center; min-width: 0; min-height: var(--oc-space-4); color: var(--oc-text-secondary); font-family: var(--font-mono); font-size: var(--oc-fs-micro); }

    .chart-legend__view { flex: 1 1 0; min-width: 0; overflow: hidden; }

    .chart-legend__track { display: flex; gap: var(--oc-space-3); margin: 0; padding: 0; list-style: none; white-space: nowrap; }

    .chart-legend__track--wrap { flex-wrap: wrap; row-gap: var(--oc-space-1); white-space: normal; }

    .chart-legend__cell { flex: none; min-width: 0; max-width: var(--legend-cap, none); }

    .chart-legend__cell--off { visibility: hidden; }

    .chart-legend__item { display: flex; align-items: center; gap: var(--oc-space-1); max-width: 100%; padding: 0; border: 0; background: none; color: inherit; font: inherit; cursor: pointer; }

    .chart-legend__item--dim { color: var(--oc-text-dim); }

    .chart-legend__item--dim .chart-legend__swatch { opacity: .35; }

    .chart-legend__item > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }

    .chart-legend__swatch { flex: none; width: var(--oc-space-2); height: var(--oc-space-1); border-radius: 1px; }

    .chart-legend__pager { display: flex; flex: none; align-items: center; gap: var(--oc-space-1); padding-left: var(--oc-space-2); }

    .chart-legend__pager--probe { position: absolute; visibility: hidden; pointer-events: none; }

    .chart-legend__step { padding: 0 var(--oc-space-1); border: 0; background: none; color: var(--oc-text-secondary); font: inherit; cursor: pointer; }

    .chart-legend__step:disabled { color: var(--oc-text-dim); cursor: default; }
  }
</style>
