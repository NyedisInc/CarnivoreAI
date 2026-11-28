
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { isLive } from './jobs-format';
  import type { JobsDelta } from './jobs-store.svelte';
  import { metricsApi, type LoadReport, type Metrics, type MetricsApi } from './metrics-api';

  interface Props {
    api?: MetricsApi;
    subscribe?: (handler: (frame: JobsDelta) => void) => (() => void) | null;
    delayMs?: number;
  }
  const { api = metricsApi, subscribe = pageSubscribe, delayMs = 10000 }: Props = $props();

  function pageSubscribe(handler: (frame: JobsDelta) => void): (() => void) | null {
    const events = (globalThis as { AppEvents?: { subscribe?(h: (f: JobsDelta) => void): () => void } }).AppEvents;
    return events?.subscribe?.((frame) => { if (frame?.type === 'pack_jobs.delta') handler(frame); }) ?? null;
  }

  let data = $state<Metrics | null>(null);
  let fleet = $state<LoadReport | null>(null);
  let error = $state<string | null>(null);

  const percent = (share: number | null): string => `${Math.round((share ?? 0) * 100)}%`;
  const hours = (minutes: number): string => String(Math.round((minutes / 60) * 10) / 10);
  const pctText = (val: number | null | undefined): string => (val == null ? '-' : `${Math.round(val)}%`);
  const empty = $derived(!!data && data.r3.share === null && !(data.p3.enough_data && data.p3.share !== null));
  const agg = $derived(fleet?.fleet_now?.aggregate ?? null);
  const funnel = $derived(fleet?.guard_health?.funnel ?? null);

  async function read(): Promise<void> {
    try {
      data = await api.read(7);
      error = null;
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.jobs.numbers.failed'));
    }
    if (api.loadReport) {
      try {
        fleet = await api.loadReport(7);
      } catch {
      }
    }
  }

  onMount(() => {
    let wait: ReturnType<typeof setTimeout> | null = null;
    void read();
    const off = subscribe((frame) => {
      if (!frame.job || isLive(frame.job)) return;
      if (wait) clearTimeout(wait);
      wait = setTimeout(() => { wait = null; void read(); }, delayMs);
    });
    return () => {
      if (wait) clearTimeout(wait);
      off?.();
    };
  });
</script>

<div class="pt-numbers" data-jobs="numbers">
  <h3 class="pl-label">{t('pack.jobs.numbers.title')}</h3>
  {#if error}<p class="pt-error" role="alert" data-jobs="numbers-error">{error}</p>{/if}
  {#if agg && agg.online_machines > 0}
    <p class="pt-note" data-jobs="numbers-fleet">
      {t('pack.jobs.numbers.fleet', {
        cpu: pctText(agg.fleet_cpu_pct),
        free_cores: String(Math.round(agg.usable_free_cores * 10) / 10),
        ram: pctText(agg.fleet_ram_pct),
        free_ram: String(Math.round(agg.usable_free_ram_gb * 10) / 10),
        online: String(agg.online_machines),
      })}
    </p>
  {/if}
  {#if data}
    {#if empty}
      <p class="pt-note" data-jobs="numbers-empty">{t('pack.jobs.numbers.empty')}</p>
    {:else}
      {#if data.r3.share !== null}
        <p class="pt-line" data-jobs="numbers-share">{t('pack.jobs.numbers.share', { share: percent(data.r3.share), days: String(data.r3.window_days) })}</p>
        <p class="pt-note" data-jobs="numbers-hours">{t('pack.jobs.numbers.hours', { remote: hours(data.r3.remote_minutes), local: hours(data.r3.local_minutes) })}</p>
      {/if}
      {#if data.p3.enough_data && data.p3.share !== null}
        <p class="pt-note" data-jobs="numbers-home">{t(data.p3.over ? 'pack.jobs.numbers.home_over' : 'pack.jobs.numbers.home', { share: percent(data.p3.share) })}</p>
      {/if}
    {/if}
  {/if}
  {#if fleet && (fleet.efficiency.p50_overhead_s !== null || fleet.utilization_history.idle_while_peer_pegged_minutes > 0)}
    <p class="pt-note" data-jobs="numbers-overhead">
      {t('pack.jobs.numbers.overhead', {
        overhead: String(fleet.efficiency.p50_overhead_s ?? 0),
        run: String(fleet.efficiency.p50_run_s ?? 0),
        waste: String(fleet.utilization_history.idle_while_peer_pegged_minutes),
      })}
    </p>
  {/if}
  {#if funnel && Object.keys(funnel).length > 0}
    <p class="pt-note" data-jobs="numbers-guard">
      {t('pack.jobs.numbers.guard', {
        blocked: String(funnel.blocked_offload ?? 0),
        gave_way: String(funnel.gave_way ?? 0),
        local: String((funnel.local_only_path ?? 0) + (funnel.below_breakeven ?? 0) + (funnel.local_fit ?? 0)),
      })}
    </p>
  {/if}
</div>
