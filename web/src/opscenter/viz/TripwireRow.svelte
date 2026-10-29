<script lang="ts">
  import { untrack } from 'svelte';
  import { ApiError } from '../api/auth.svelte';
  import type { ChartConfig, ChartSeries } from '../cells/analytics/types';
  import { t } from '../../lib/i18n/index.svelte';
  import Button from '../../lib/base/Button.svelte';
  import Checkbox from '../../lib/base/Checkbox.svelte';
  import NumberField from '../../lib/base/NumberField.svelte';
  import Select from '../../lib/base/Select.svelte';
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
  let threshold = $state<number | null>(seed.threshold);
  let windowMinutes = $state<number | null>(seed.window);
  let forMinutes = $state<number | null>(seed.hold);
  let cooldown = $state<number | null>(seed.cooldown);
  let enabled = $state(seed.enabled);
  let busy = $state(false);
  let failure = $state('');

  async function save(): Promise<void> {
    if (threshold === null || !Number.isFinite(threshold)) { failure = t('tripwire.bad_threshold'); return; }
    busy = true;
    failure = '';
    try {
      await saveTripwire(wire?.id ?? null, {
        chart_id: config.id, name: (config.title || series.metric).slice(0, 80),
        query: tripwireQuery(config, series, { now: chartTick({ series: [series] }), timezone: analytics.timezone, filters: analytics.filters }),
        window_minutes: windowMinutes as number, comparator, threshold: toStored(threshold, unit), for_minutes: forMinutes as number, cooldown_minutes: cooldown as number, enabled,
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
  <Select size="sm" label={t('tripwire.when')} aria-label={t('tripwire.comparator')} bind:value={comparator}
    options={[{ value: '>', label: t('tripwire.above') }, { value: '<', label: t('tripwire.below') }]} />
  <NumberField size="sm" label={`${t('tripwire.threshold')} ${caption}`.trim()} bind:value={threshold} data-tripwire-threshold="" />
  <NumberField size="sm" label={t('tripwire.window')} min={1} max={1440} bind:value={windowMinutes} />
  <NumberField size="sm" label={t('tripwire.hold')} min={0} max={1440} bind:value={forMinutes} data-tripwire-for="" />
  <NumberField size="sm" label={t('tripwire.cooldown')} min={0} max={10080} bind:value={cooldown} />
  <Checkbox label={t('analytics.enabled')} bind:checked={enabled} />
  <span class="tw-row__actions">
    <Button variant="confirm" disabled={busy} onclick={() => void save()} data-tripwire-save="">{t('analytics.save')}</Button>
    <Button variant="danger" disabled={busy} onclick={() => void remove()}>{wire ? t('analytics.remove') : t('tripwire.cancel')}</Button>
  </span>
  {#if failure}<p class="tw-row__note" role="alert">{failure}</p>{/if}
</div>

<style>
  @layer components {
    .tw-row { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--oc-space-2); flex-basis: 100%; padding: var(--oc-space-2) 0; box-shadow: 0 -1px 0 var(--oc-line-rule); }

    .tw-row__actions { display: flex; gap: var(--oc-space-2); margin-left: auto; }

    .tw-row__note { flex-basis: 100%; margin: 0; color: var(--oc-coral); font: var(--oc-fs-label) var(--font-mono); }
  }
</style>
