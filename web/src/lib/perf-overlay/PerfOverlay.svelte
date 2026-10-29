<script lang="ts">
  import { onDestroy } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { probe } from './boot';
  import type { PerfClientSnapshot, PerfServerSample } from './types';

  const RENDER_TICK_MS = 1000;

  let snap = $state<PerfClientSnapshot | null>(null);
  let open = $state(true);

  function read(): void {
    snap = probe()?.snapshot() ?? null;
  }
  read();
  const tick = setInterval(read, RENDER_TICK_MS);
  const off = probe()?.onServerSample(() => read()) ?? (() => {});
  onDestroy(() => {
    clearInterval(tick);
    off();
  });

  const server = $derived<PerfServerSample | null>(snap?.server ?? null);
  const rxBytes = $derived(snap ? snap.rx.reduce((sum, r) => sum + r.bytes_per_s, 0) : 0);
  const rxMsgs = $derived(snap ? snap.rx.reduce((sum, r) => sum + r.msgs_per_s, 0) : 0);

  function n(value: number | null | undefined, digits = 0): string {
    return value === null || value === undefined ? '-' : value.toFixed(digits);
  }
</script>

<section class="perf-ov" aria-label={t('perf.overlay.title')}>
  <header class="perf-ov__bar">
    <span class="perf-ov__title">{t('perf.overlay.title')}</span>
    <button type="button" class="perf-ov__toggle" onclick={() => (open = !open)}>
      {open ? t('perf.overlay.hide') : t('perf.overlay.show')}
    </button>
  </header>
  {#if open && snap}
    <dl class="perf-ov__grid">
      <dt>{t('perf.overlay.echo')}</dt>
      <dd>{n(snap.echo.net_ms, 1)} / {n(snap.echo.painted_ms, 1)} ms ({t('perf.overlay.worst')} {n(snap.echo.worst_ms, 0)}, n={snap.echo.samples})</dd>
      <dt>{t('perf.overlay.received')}</dt>
      <dd>{n(rxMsgs, 1)} msg/s, {n(rxBytes, 0)} B/s</dd>
      <dt>{t('perf.overlay.frames')}</dt>
      <dd>{n(snap.frames_per_s, 1)}/s</dd>
      <dt>{t('perf.overlay.loop_lag')}</dt>
      <dd>{n(server?.loop_lag_ms.p50, 1)} / {n(server?.loop_lag_ms.p99, 1)} / {n(server?.loop_lag_ms.minute_max, 0)} ms</dd>
      <dt>{t('perf.overlay.server')}</dt>
      <dd>{n(server?.processes?.server?.cpu_pct, 1)}% cpu, {n(server?.processes?.server?.rss_mb, 0)} MB, {n(server?.requests_per_min, 0)} req/min</dd>
      <dt>{t('perf.overlay.watcher')}</dt>
      <dd>{n(server?.watcher_ms?.full?.p50, 1)} ms ({t('perf.overlay.worst')} {n(server?.watcher_ms?.full?.max, 0)})</dd>
    </dl>
    <div class="perf-ov__label">{t('perf.overlay.pollers')} ({snap.pollers.length})</div>
    <ul class="perf-ov__list">
      {#each snap.pollers as p, i (i)}
        <li><span class="perf-ov__ms">{p.ms} ms</span> {p.name}</li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  @layer components {
  .perf-ov {
    position: fixed;
    right: 8px;
    bottom: 8px;
    z-index: 9998;
    width: 340px;
    max-height: 60vh;
    overflow: auto;
    font-family: var(--font-mono);
    font-size: var(--oc-fs-micro);
    color: var(--oc-text-primary);
    background: var(--oc-ground-raised);
    border: var(--oc-border) solid var(--oc-line-frame);
    border-radius: var(--oc-radius-sm);
  }
  .perf-ov__bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 24px;
    padding: 0 8px;
    background: var(--oc-ground-titlerow);
    box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
  }
  .perf-ov__title {
    color: var(--oc-orange);
    text-transform: uppercase;
    letter-spacing: var(--oc-tracking-label);
  }
  .perf-ov__toggle {
    font: inherit;
    color: var(--oc-text-secondary);
    background: transparent;
    border: var(--oc-border) solid var(--oc-line-frame);
    border-radius: var(--oc-radius-sm);
    padding: 0 6px;
    cursor: pointer;
  }
  .perf-ov__grid {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 2px 8px;
    margin: 0;
    padding: 6px 8px;
    box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
  }
  .perf-ov__grid dt {
    color: var(--oc-text-secondary);
  }
  .perf-ov__grid dd {
    margin: 0;
  }
  .perf-ov__label {
    padding: 4px 8px 0;
    color: var(--oc-text-secondary);
    text-transform: uppercase;
    letter-spacing: var(--oc-tracking-label);
  }
  .perf-ov__list {
    list-style: none;
    margin: 0;
    padding: 2px 8px 6px;
  }
  .perf-ov__list li {
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .perf-ov__ms {
    color: var(--oc-text-secondary);
  }
  }
</style>
