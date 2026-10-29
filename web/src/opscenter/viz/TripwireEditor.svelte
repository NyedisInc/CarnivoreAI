<script lang="ts">
  import type { ChartConfig } from '../cells/analytics/types';
  import { analytics } from '../cells/analytics/state.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import TripwireRow from './TripwireRow.svelte';
  import { seriesUnit } from './tripwire-model';
  import { tripwires } from './tripwires.svelte';

  let { config }: { config: ChartConfig } = $props();
  let adding = $state(false);
  const series = $derived(config.series.find((item) => item.visible !== false));
  const unit = $derived(series ? seriesUnit(Object.fromEntries(analytics.catalog.map((entry) => [entry.id, entry.unit ?? ''])), series) : '');
  const wires = $derived(tripwires.list.filter((wire) => wire.chart_id === config.id));
</script>

<div class="tw-edit" aria-label={t('tripwire.title')} data-tripwire-editor="">
  <div class="tw-edit__head"><span>{t('tripwire.title')}</span>
    {#if series && config.revision >= 1 && !adding}<button type="button" class="modal-btn modal-btn-secondary" onclick={() => { adding = true; }} data-tripwire-add="">{t('tripwire.add')}</button>{/if}
  </div>
  {#if !series}
    <p class="tw-edit__note">{t('tripwire.no_series')}</p>
  {:else if config.revision < 1}
    <p class="tw-edit__note">{t('tripwire.save_first')}</p>
  {:else}
    {#each wires as wire (wire.id)}<TripwireRow {config} {series} {unit} {wire} />{/each}
    {#if adding}<TripwireRow {config} {series} {unit} ondone={() => { adding = false; }} />{/if}
  {/if}
</div>

<style>
  @layer components {
    .tw-edit { flex-basis: 100%; display: flex; flex-direction: column; gap: var(--oc-space-1); padding-top: var(--oc-space-2); box-shadow: 0 -1px 0 var(--oc-line-rule); }

    .tw-edit__head { display: flex; align-items: center; justify-content: space-between; color: var(--oc-orange); font: var(--oc-fs-micro) var(--font-mono); letter-spacing: .08em; text-transform: uppercase; }

    .tw-edit__note { margin: 0; color: var(--oc-text-muted); font: var(--oc-fs-label) var(--font-mono); }
  }
</style>
