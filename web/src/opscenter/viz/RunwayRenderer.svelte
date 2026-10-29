<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { windowLabel } from './dimension-label';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import { paceOf } from '../../../../client/js/labels/pace.js';
  import { WINDOW_SCALE_STOPS, scaleStepFor, windowMeterText } from '../../../../client/js/labels/usage-panel.js';
  import { ledger } from '../api';
  import { analytics } from '../cells/analytics/state.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import LimitGauge from '../ui/LimitGauge.svelte';
  import VizSettings from './VizSettings.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { formatDuration, formatMetric } from './format';
  import { defaultQuotaWindow, runwayPlan } from './plan';
  import { planQuery } from './plan-query.svelte';
  import { byUrgency, runwayModel, type RunwayRow } from './runway';
  import { watchVisible } from './visible';
  import { wholeItems } from './whole-items';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let visible = $state(false);
  onMount(() => watchVisible(root, (value) => { visible = value; }));
  const quotaWindow = $derived(defaultQuotaWindow(analytics.dimensions) ?? null);
  const read = planQuery(
    () => ({ on: config.enabled, items: runwayPlan(config, { now: analytics.tickAt, timezone: analytics.timezone, filters: analytics.filters, quotaWindow: quotaWindow ?? undefined }) }),
    () => visible,
  );
  const series = $derived(read.outcomes?.[0]?.ok ? read.outcomes[0].result.series : []);
  const message = $derived(read.failure || (read.outcomes?.[0] && !read.outcomes[0].ok ? read.outcomes[0].error.message : ''));
  const rows = $derived(byUrgency(runwayModel(ledger.data?.accounts ?? [], series, quotaWindow, analytics.tickAt))
    .filter((row) => row.verdict !== 'unknown' || row.usedPct !== null || row.resetSeconds !== null));
  const accounts = $derived(ledger.data?.accounts?.length ?? 0);

  function verdictText(row: RunwayRow): string {
    const reset = row.resetSeconds === null ? null : formatDuration(row.resetSeconds);
    switch (row.verdict) {
      case 'hits_first': return t('runway.hits', { left: formatDuration(row.toLimitSeconds ?? 0), reset: reset ?? '' });
      case 'resets_first': return t('runway.clear', { reset: reset ?? '' });
      case 'idle': return reset ? t('runway.idle', { reset }) : t('runway.idle_no_reset');
      case 'full': return reset ? t('runway.full', { reset }) : t('runway.full_no_reset');
      default: return reset ? t('runway.unknown_reset', { reset }) : '';
    }
  }

  function gauge(row: RunwayRow): { pct: number; scale: number | null; elapsed: number | null; state: string | null; text: string } {
    const pct = row.usedPct as number;
    const window = row.window as NonNullable<RunwayRow['window']>;
    const pace = paceOf(window, analytics.tickAt, scaleStepFor(pct, WINDOW_SCALE_STOPS));
    return { pct, scale: pace.scale, elapsed: pace.elapsedPct, state: pace.state, text: windowMeterText(window.label, pct, pace, t) };
  }
</script>

<section bind:this={root} class="viz-runway viz-runway--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-runway__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-runway__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile' && quotaWindow}<span>{windowLabel(quotaWindow)}</span>{/if}</header>
    {#if message}<p class="viz-runway__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
    {#if rows.length === 0}
      {#if ledger.status === 'ok'}<EmptyState line={emptyLine(accounts ? 'quota' : 'accounts')} />{/if}
    {:else}
      <ul class="viz-runway__rows" data-runway="rows" use:wholeItems={{ enabled: tier === 'tile' }}>
        {#each rows as row (row.id)}
          <li class="viz-runway__row" data-runway-row={row.id} data-verdict={row.verdict}>
            <span class="viz-runway__name" title={row.name}>{row.name}</span>
            {#if tier !== 'tile' && row.window && row.usedPct !== null}
              {@const g = gauge(row)}
              <span class="viz-runway__gauge"><LimitGauge variant="fill" pct={g.pct} scale={g.scale} paceElapsedPct={g.elapsed} paceState={g.state} meterText={g.text} height={6} /></span>
              <span class="viz-runway__pct">{formatMetric(row.usedPct, 'percent').text}</span>
            {/if}
            <span class="viz-runway__verdict viz-runway__verdict--{row.verdict}">{verdictText(row)}</span>
            {#if tier === 'full'}<span class="viz-runway__burn">{row.burnPerHour === null ? '' : t('runway.burn', { value: formatMetric(row.burnPerHour, 'percent').text })}</span>{/if}
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
  <VizSettings {config} metric={false} />
</section>

<style>
  @layer components {
    .viz-runway { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-runway__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-runway__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-runway__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-runway__rows { flex: 1; min-height: 0; margin: 0; padding: 0; overflow: auto; list-style: none; }

    .viz-runway--tile .viz-runway__rows { overflow: hidden; }

    .viz-runway__row { display: flex; align-items: center; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-runway__name { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-runway__gauge { flex: 2 1 6ch; min-width: 0; }

    .viz-runway__pct { flex: none; min-width: 6ch; font-variant-numeric: tabular-nums; text-align: right; }

    .viz-runway__verdict { flex: 2 1 12ch; min-width: 0; overflow: hidden; color: var(--oc-text-muted); text-overflow: ellipsis; white-space: nowrap; }

    .viz-runway__verdict--hits_first { color: var(--oc-yellow); }

    .viz-runway__verdict--full { color: var(--oc-coral); }

    .viz-runway__verdict--resets_first, .viz-runway__verdict--idle { color: var(--oc-text-secondary); }

    .viz-runway__burn { flex: none; color: var(--oc-text-muted); }

    .viz-runway__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
