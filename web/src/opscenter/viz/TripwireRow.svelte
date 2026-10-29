<script lang="ts">
  import { untrack } from 'svelte';
  import { ApiError } from '../api/auth.svelte';
  import type { ChartConfig, ChartSeries } from '../cells/analytics/types';
  import { t } from '../../lib/i18n/index.svelte';
  import { analytics, chartTick } from '../cells/analytics/state.svelte';
  import { displayUnit, toDisplay, toStored, tripwireQuery, type Tripwire } from './tripwire-model';
  import { removeTripwire, saveTripwire } from './tripwires.svelte';

  let { config, series, unit, wire = null, ondone }: { config: ChartConfig; series: ChartSeries; unit: string; wire?: Tripwire | null; ondone?: () => void } = $props();
  const caption = $derived(displayUnit(unit).caption);
  const seed = untrack(() => ({
    comparator: wire?.comparator ?? '>', threshold: wire ? toDisplay(wire.threshold, unit) : 0,
    window: wire?.window_minutes ?? 15, hold: wire?.for_minutes ?? 5, cooldown: wire?.cooldown_minutes ?? 30, enabled: wire?.enabled ?? true,
  }));
  let comparator = $state<'>' | '<'>(seed.comparator);
  let threshold = $state(seed.threshold);
  let windowMinutes = $state(seed.window);
  let forMinutes = $state(seed.hold);
  let cooldown = $state(seed.cooldown);
  let enabled = $state(seed.enabled);
  let busy = $state(false);
  let failure = $state('');

  async function save(): Promise<void> {
    if (!Number.isFinite(threshold)) { failure = t('tripwire.bad_threshold'); return; }
    busy = true;
    failure = '';
    try {
      await saveTripwire(wire?.id ?? null, {
        chart_id: config.id, name: (config.title || series.metric).slice(0, 80),
        query: tripwireQuery(config, series, { now: chartTick({ series: [series] }), timezone: analytics.timezone, filters: analytics.filters }),
        window_minutes: windowMinutes, comparator, threshold: toStored(threshold, unit), for_minutes: forMinutes, cooldown_minutes: cooldown, enabled,
      });
      ondone?.();
    } catch (cause) {
      failure = cause instanceof ApiError || cause instanceof Error ? cause.message : t('tripwire.save_failed');
    } finally { busy = false; }
  }

  async function remove(): Promise<void> {
    if (!wire) { ondone?.(); return; }
    busy = true;
    failure = '';
    try { await removeTripwire(wire.id); } catch (cause) { failure = cause instanceof Error ? cause.message : t('tripwire.save_failed'); busy = false; }
  }
</script>

<div class="tw-row" data-tripwire-row={wire?.id ?? 'new'}>
  <label class="tw-row__field">{t('tripwire.when')}
    <select class="oc-field" bind:value={comparator} aria-label={t('tripwire.comparator')}><option value=">">{t('tripwire.above')}</option><option value="<">{t('tripwire.below')}</option></select>
  </label>
  <label class="tw-row__field">{t('tripwire.threshold')} {caption}
    <input class="oc-field" type="number" step="any" bind:value={threshold} data-tripwire-threshold="" />
  </label>
  <label class="tw-row__field">{t('tripwire.window')}<input class="oc-field" type="number" min="1" max="1440" bind:value={windowMinutes} /></label>
  <label class="tw-row__field">{t('tripwire.hold')}<input class="oc-field" type="number" min="0" max="1440" bind:value={forMinutes} data-tripwire-for="" /></label>
  <label class="tw-row__field">{t('tripwire.cooldown')}<input class="oc-field" type="number" min="0" max="10080" bind:value={cooldown} /></label>
  <label class="tw-row__field tw-row__check"><input type="checkbox" bind:checked={enabled} /> {t('analytics.enabled')}</label>
  <span class="tw-row__actions">
    <button type="button" class="modal-btn modal-btn-confirm" disabled={busy} onclick={() => void save()} data-tripwire-save="">{t('analytics.save')}</button>
    <button type="button" class="modal-btn modal-btn-danger" disabled={busy} onclick={() => void remove()}>{wire ? t('analytics.remove') : t('tripwire.cancel')}</button>
  </span>
  {#if failure}<p class="tw-row__note" role="alert">{failure}</p>{/if}
</div>

<style>
  @layer components {
    .tw-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--oc-space-2); flex-basis: 100%; padding: var(--oc-space-2) 0; box-shadow: 0 -1px 0 var(--oc-line-rule); }

    .tw-row__field { display: flex; flex-direction: column; gap: var(--oc-space-1); color: var(--oc-text-muted); font: var(--oc-fs-micro) var(--font-mono); letter-spacing: .08em; text-transform: uppercase; }

    .tw-row__field input[type='number'] { width: 7ch; }

    .tw-row__check { flex-direction: row; align-items: center; }

    .tw-row__actions { display: flex; gap: var(--oc-space-2); margin-left: auto; }

    .tw-row__note { flex-basis: 100%; margin: 0; color: var(--oc-coral); font: var(--oc-fs-label) var(--font-mono); }
  }
</style>
