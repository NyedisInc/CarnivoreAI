
<script lang="ts">
  import { onMount } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
  import { isLive } from './jobs-format';
  import type { JobsDelta } from './jobs-store.svelte';
  import { metricsApi, type Metrics, type MetricsApi } from './metrics-api';

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
  let error = $state<string | null>(null);

  const percent = (share: number | null): string => `${Math.round((share ?? 0) * 100)}%`;
  const hours = (minutes: number): string => String(Math.round((minutes / 60) * 10) / 10);
  const empty = $derived(!!data && data.r3.share === null && !(data.p3.enough_data && data.p3.share !== null));

  async function read(): Promise<void> {
    try {
      data = await api.read(7);
      error = null;
    } catch (failure) {
      error = nonEmptyErrorMessageOr(failure, t('pack.jobs.numbers.failed'));
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
</div>
