<script lang="ts">
  import type { SlotId } from '../engine/types';
  import { analytics } from '../cells/analytics/state.svelte';
  import { GALLERY_CATEGORIES, PRESETS, presetNoteKey, presetTitleKey, type GalleryCategory } from '../viz/presets';
  import { manifestById } from '../widgets/core-manifests';
  import { passesFilter, type DrawerInputs } from './drawer-model';
  import { addAnalyticsWidget, addGalleryPreset, hideAnalyticsWidget, removeWidget, restoreAnalyticsWidget } from './editor.svelte';
  import ChartDeleteChip from './ChartDeleteChip.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    open,
    needle,
    matchesFamily,
    inputs,
    onSurface,
  }: {
    open: boolean;
    needle: string;
    matchesFamily: boolean;
    inputs: Pick<DrawerInputs, 'query' | 'category'>;
    onSurface: readonly SlotId[];
  } = $props();

  let galleryCategory = $state<GalleryCategory | null>(null);
  const analyticsCategory = manifestById('core.analytics')!.category;

  const galleryCards = $derived.by(() => {
    const kept = PRESETS.filter((preset) => !galleryCategory || preset.category === galleryCategory);
    if (!needle) return kept;
    const hits = kept.filter((preset) => `${t(presetTitleKey(preset))} ${t(presetNoteKey(preset))} ${preset.viz}`.toLowerCase().includes(needle));
    return hits.length ? hits : kept;
  });
  const shownCharts = $derived(
    Object.values(analytics.charts).filter((chart) => matchesFamily || passesFilter(inputs, analyticsCategory, [chart.title])),
  );
</script>

{#if open}
  <li class="le-gallery" aria-label={t('gallery.title')} data-analytics-fold>
    <p class="le-gallery__label">{t('gallery.title')}</p>
    <div class="le-gallery__cats" role="group" aria-label={t('gallery.cats')}>
      {#each GALLERY_CATEGORIES as name (name)}
        <button type="button" class="le-chip" class:le-chip--on={galleryCategory === name} aria-pressed={galleryCategory === name} data-gallery-category={name}
          onclick={() => (galleryCategory = galleryCategory === name ? null : name)}>{t(`gallery.cat.${name}`)}</button>
      {/each}
    </div>
    <ul class="le-gallery__cards">
      {#each galleryCards as preset (preset.id)}
        <li><button type="button" class="le-card le-gallery__card" data-preset={preset.id} data-viz={preset.viz} title={t(presetNoteKey(preset))} onclick={() => addGalleryPreset(preset)}>
          <span class="le-gallery__plus" aria-hidden="true">+</span>
          <span class="le-gallery__text"><span class="le-gallery__name">{t(presetTitleKey(preset))}</span><span class="le-gallery__note"
              ><span class="le-gallery__viz">{t(`viz.${preset.viz}`)}</span><span class="le-gallery__sep" aria-hidden="true">·</span>{t(presetNoteKey(preset))}</span
            ></span>
        </button></li>
      {/each}
    </ul>
    <p class="le-gallery__hint">{t('gallery.hint')}</p>
    {#if shownCharts.length > 0}
      <p class="le-gallery__label">{t('gallery.yours')}</p>
      <ul class="le-gallery__charts">
        {#each shownCharts as chart (chart.id)}
          {@const slot = `analytics:${chart.id}` as SlotId}
          {@const placed = onSurface.includes(slot)}
          <li class="le-chart-row" class:le-chart-row--hidden={!placed} data-analytics-chart={chart.id}>
            <span class="le-chart-row__name" title={chart.title}>{chart.title}</span>
            <span class="le-chart-row__acts">
              {#if placed}
                <button type="button" class="le-chip" onclick={() => addAnalyticsWidget(chart)}>{t('analytics.duplicate')}</button>
                <button type="button" class="le-chip" onclick={() => hideAnalyticsWidget(slot)}>{t('analytics.hide')}</button>
                <button type="button" class="le-chip" onclick={() => void removeWidget(slot)}>{t('analytics.remove')}</button>
              {:else}
                <button type="button" class="le-chip" onclick={() => restoreAnalyticsWidget(slot)}>{t('analytics.restore')}</button>
                <ChartDeleteChip chartId={chart.id} />
              {/if}
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  </li>
{/if}

<style>
  @layer components {
  .le-gallery {
    display: flex;
    flex-direction: column;
    gap: var(--oc-space-1);
    margin: 2px 0 var(--oc-space-2) 22px;
    padding: var(--oc-space-1) 0 var(--oc-space-1) var(--oc-space-2);
    box-shadow: inset 1px 0 0 var(--oc-line-rule);
    min-width: 0;
  }

  .le-gallery__label {
    margin: var(--oc-space-1) 0 0;
    padding: 0 6px;
    font-size: var(--oc-fs-micro);
    letter-spacing: var(--oc-tracking-label, 0.6px);
    text-transform: uppercase;
    color: var(--oc-text-muted);
  }

  .le-gallery__cats {
    display: flex;
    flex-wrap: wrap;
    gap: var(--oc-space-1);
    padding: 0 6px;
  }

  .le-gallery__cards,
  .le-gallery__charts {
    display: flex;
    flex-direction: column;
    gap: 1px;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  :global(.le-drawer) .le-gallery__card {
    align-items: flex-start;
    gap: var(--oc-space-2);
    padding: var(--oc-space-1) 6px;
  }

  .le-gallery__plus {
    flex: none;
    width: 10px;
    font-size: var(--oc-fs-body);
    line-height: 16px;
    color: var(--oc-text-muted);
  }

  :global(.le-drawer) .le-gallery__card:hover .le-gallery__plus,
  :global(.le-drawer) .le-gallery__card:focus-visible .le-gallery__plus {
    color: var(--oc-green);
  }

  .le-gallery__text {
    display: flex;
    flex-direction: column;
    gap: 1px;
    min-width: 0;
  }

  .le-gallery__name {
    overflow: hidden;
    font-size: var(--oc-fs-body);
    line-height: 16px;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--oc-text-primary);
  }

  .le-gallery__note {
    overflow: hidden;
    font-size: var(--oc-fs-label);
    line-height: 14px;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--oc-text-muted);
  }

  .le-gallery__viz {
    color: var(--oc-text-secondary);
  }

  .le-gallery__sep {
    padding: 0 3px;
    color: var(--oc-text-muted);
  }

  .le-gallery__hint {
    margin: 0;
    padding: 2px 6px;
    font-size: var(--oc-fs-label);
    color: var(--oc-text-muted);
  }

  .le-chart-row {
    display: flex;
    align-items: center;
    gap: var(--oc-space-2);
    min-height: 26px;
    padding: 2px 6px;
    border-radius: var(--oc-radius-sm, 2px);
  }

  .le-chart-row:hover {
    background: var(--oc-ground-hover);
  }

  .le-chart-row__name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    font-size: var(--oc-fs-body);
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--oc-text-primary);
  }

  .le-chart-row--hidden .le-chart-row__name {
    color: var(--oc-text-muted);
  }

  .le-chart-row__acts {
    display: inline-flex;
    flex: none;
    gap: var(--oc-space-1);
  }
  }
</style>
