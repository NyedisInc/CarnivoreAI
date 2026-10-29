<script lang="ts">
  import type { Snippet } from 'svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import type { ChartConfig, RangePreset, Viz } from '../cells/analytics/types';
  import { changeAnalyticsConfig } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';
  import Field from '../../lib/base/Field.svelte';
  import Select from '../../lib/base/Select.svelte';
  import TripwireEditor from './TripwireEditor.svelte';
  import { VIZ_SPECS, vizOf } from './specs';
  import { metricOptions, rangeOptions, vizKindOptions } from './settings-options';
  import { declareSettingsPanel } from '../widgets/chrome/settings-panels.svelte';

  let { config, metric = true, group = false, range = true, tripwire = false, children }: { config: ChartConfig; metric?: boolean; group?: boolean; range?: boolean; tripwire?: boolean; children?: Snippet } = $props();
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
    <Field label={t('analytics.title')} maxlength={80} value={config.title} oninput={(event) => edit({ title: event.currentTarget.value })} />
    <Select size="sm" label={t('viz.kind')} value={vizOf(config)} options={vizKindOptions()} onchange={(event) => edit({ viz: event.currentTarget.value as Viz, options: { ...VIZ_SPECS[event.currentTarget.value as Viz].options } })} />
    {#if metric}
      <Select size="sm" label={t('analytics.metric')} value={series?.metric ?? ''} options={metricOptions(analytics.catalog)} onchange={(event) => editSeries({ metric: event.currentTarget.value, group_by: undefined, transform: event.currentTarget.value === 'quota_utilization' || event.currentTarget.value.startsWith('average_') ? 'total' : series?.transform })} />
    {/if}
    {#if group}
      <Select size="sm" label={t('analytics.group')} value={series?.group_by ?? ''} options={groups.map((name) => ({ value: name, label: name }))} onchange={(event) => editSeries({ group_by: event.currentTarget.value || undefined })} />
    {/if}
    {#if range}
      <Select size="sm" label={t('analytics.range')} value={config.range.preset ?? ''} options={rangeOptions()} onchange={(event) => edit({ range: { ...config.range, preset: (event.currentTarget.value || null) as RangePreset | null, zoom: null } })} />
    {/if}
    {@render children?.()}
    <Checkbox label={t('analytics.enabled')} checked={config.enabled} onchange={(event) => edit({ enabled: event.currentTarget.checked })} />
    {#if tripwire}<TripwireEditor {config} />{/if}
  </div>
{/snippet}

<style>
  @layer components {
    .viz-set { display: flex; align-items: center; flex-wrap: wrap; gap: var(--oc-space-2); color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }
  }
</style>
