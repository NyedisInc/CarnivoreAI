<script lang="ts">
  import type { Snippet } from 'svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import type { ChartConfig, RangePreset, Viz } from '../cells/analytics/types';
  import { changeAnalyticsConfig } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';
  import { PRESET_MS } from './plan';
  import TripwireEditor from './TripwireEditor.svelte';
  import { VIZ_KINDS, VIZ_SPECS, vizOf } from './specs';
  import { declareSettingsPanel } from '../widgets/chrome/settings-panels.svelte';

  let { config, metric = true, group = false, range = true, tripwire = false, children }: { config: ChartConfig; metric?: boolean; group?: boolean; range?: boolean; tripwire?: boolean; children?: Snippet } = $props();
  const PRESETS = Object.keys(PRESET_MS) as RangePreset[];
  const series = $derived(config.series.find((item) => item.visible !== false));
  const groups = $derived(analytics.catalog.find((entry) => entry.id === series?.metric)?.group_by ?? []);

  function edit(next: Partial<ChartConfig>): void {
    changeAnalyticsConfig({ ...config, ...next });
  }

  function editSeries(patch: Partial<ChartConfig['series'][number]>): void {
    edit({ series: config.series.map((item) => item === series ? { ...item, ...patch } : item) });
  }

  $effect(() => declareSettingsPanel(`analytics:${config.id}`, panel));
</script>

{#snippet panel()}
  <div class="viz-set" data-instance-settings="" aria-label={t('analytics.chart_settings')}>
    <label>{t('analytics.title')} <input maxlength="80" value={config.title} oninput={(event) => edit({ title: event.currentTarget.value })} /></label>
    <label>{t('viz.kind')} <select value={vizOf(config)} onchange={(event) => edit({ viz: event.currentTarget.value as Viz, options: { ...VIZ_SPECS[event.currentTarget.value as Viz].options } })}>
      {#each VIZ_KINDS as kind (kind)}<option value={kind}>{t(`viz.${kind}`)}</option>{/each}
    </select></label>
    {#if metric}
      <label>{t('analytics.metric')} <select value={series?.metric ?? ''} onchange={(event) => editSeries({ metric: event.currentTarget.value, group_by: undefined, transform: event.currentTarget.value === 'quota_utilization' || event.currentTarget.value.startsWith('average_') ? 'total' : series?.transform })}>
        {#each analytics.catalog as entry (entry.id)}<option value={entry.id}>{entry.label || entry.id}</option>{/each}
      </select></label>
    {/if}
    {#if group}
      <label>{t('analytics.group')} <select value={series?.group_by ?? ''} onchange={(event) => editSeries({ group_by: event.currentTarget.value || undefined })}>
        {#each groups as name (name)}<option value={name}>{name}</option>{/each}
      </select></label>
    {/if}
    {#if range}
    <label>{t('analytics.range')} <select value={config.range.preset ?? ''} onchange={(event) => edit({ range: { ...config.range, preset: (event.currentTarget.value || null) as RangePreset | null, zoom: null } })}>
      <option value="">{t('analytics.range_global')}</option>{#each PRESETS as item (item)}<option value={item}>{t(`analytics.preset_${item}`)}</option>{/each}
    </select></label>
    {/if}
    {@render children?.()}
    <Checkbox label={t('analytics.enabled')} checked={config.enabled} onchange={(event) => edit({ enabled: event.currentTarget.checked })} />
    {#if tripwire}<TripwireEditor {config} />{/if}
  </div>
{/snippet}

<style>
  @layer components {
    .viz-set { display: flex; align-items: center; flex-wrap: wrap; gap: var(--oc-space-2); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-set label { display: flex; align-items: center; gap: var(--oc-space-1); }

    .viz-set select, .viz-set input:not([type='checkbox']) { min-height: var(--oc-space-5); padding: 0 var(--oc-space-2); border: 1px solid var(--oc-line-rule); border-radius: var(--oc-radius-sm); background: var(--oc-ground-raised); color: var(--oc-text-primary); font: inherit; }
  }
</style>
