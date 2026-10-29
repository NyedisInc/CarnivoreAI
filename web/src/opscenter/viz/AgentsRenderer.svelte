<script lang="ts">
  import { onMount } from 'svelte';
  import { sessions } from '../api';
  import ChartCanvas from '../cells/analytics/ChartCanvas.svelte';
  import { analytics, chartTick } from '../cells/analytics/state.svelte';
  import type { ChartConfig, QueryResult } from '../cells/analytics/types';
  import { changeAnalyticsConfig } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import ChartFrame from '../../lib/base/ChartFrame.svelte';
  import Segmented from '../../lib/base/Segmented.svelte';
  import { useHeaderGroup } from '../shell/frame-header.svelte';
  import { seriesBlank } from './empty';
  import { AGENT_WINDOWS, OTHER_KEY, agentChart, agentWindow, agentsPlan, liveAgents } from './agents';
  import EmptyState from './EmptyState.svelte';
  import type { Tier } from './density';
  import { formatSi } from './format';
  import { live, watchLive } from './noc-feed.svelte';
  import { planQuery } from './plan-query.svelte';
  import VizSettings from './VizSettings.svelte';
  import { watchVisible } from './visible';
  import { wholeItems } from './whole-items';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  let root = $state<HTMLElement | undefined>();
  let visible = $state(false);
  onMount(() => (root ? watchVisible(root, (value) => { visible = value; }) : undefined));
  $effect(() => (config.enabled && visible ? watchLive() : undefined));

  const span = $derived(agentWindow(config));
  const read = planQuery(
    () => ({ on: config.enabled, tick: chartTick(config), items: agentsPlan(config, { now: chartTick(config), timezone: analytics.timezone, filters: analytics.filters }) }),
    () => visible,
  );
  const answer = $derived<QueryResult | null>(read.outcomes?.[0]?.ok ? read.outcomes[0].result : null);
  const failed = $derived(read.outcomes?.find((item) => !item.ok));
  const message = $derived(read.failure || (failed && !failed.ok ? failed.error.message : ''));
  const chart = $derived(agentChart(answer));
  const looks = $derived(new Map(chart.lines.map((line) => [line.key, { color: line.color, dashed: line.other }])));
  const drawConfig = $derived<ChartConfig>({ ...config, display: { ...config.display, type: 'line', stacked: false, legend: true } });
  const rows = $derived(liveAgents(live.data, sessions.data));
  const place = useHeaderGroup(() => (config.enabled ? windowGroup : null));

  function pick(next: (typeof AGENT_WINDOWS)[number]): void {
    if (next !== span) changeAnalyticsConfig({ ...config, range: { ...config.range, preset: next, zoom: null } });
  }
</script>

{#snippet windowGroup()}
  <Segmented
    label={t('agents.window.label')}
    data-agents-window
    options={AGENT_WINDOWS.map((option) => ({ value: option, label: t(`agents.window.${option}`), attrs: { 'data-window': option, title: t(`analytics.preset_${option}`) } }))}
    bind:value={() => span, (next) => pick(next as (typeof AGENT_WINDOWS)[number])}
    onmousedown={(event) => event.preventDefault()}
  />
{/snippet}

<ChartFrame bind:element={root} size={tier} label={config.title} class="viz-agents">
  {#if !config.enabled}
    <p class="oc-chart-frame__note">{t('analytics.chart_disabled')}</p>
  {:else}
    {#if !place.up}<div class="oc-chart-frame__head viz-agents__head">{@render windowGroup()}</div>{/if}
    {#if message}<p class="oc-chart-frame__context viz-agents__note" role="alert">{t('viz.item_failed', { message })}</p>{/if}
    <div class="oc-chart-frame__plot viz-agents__plot" data-agents-chart>
      {#if chart.result && !seriesBlank([chart.result])}
        <ChartCanvas config={drawConfig} results={[chart.result]} seriesConfigs={drawConfig.series} compact lookFor={(key) => looks.get(key) ?? null} wrapLegend />
      {:else if chart.result}
        <div class="oc-chart-frame__empty"><EmptyState line={t('agents.chart_empty')} /></div>
      {/if}
    </div>
    <section class="viz-agents__live" aria-label={t('agents.live_title')} data-agents-live>
      <header class="viz-agents__livehead">{t('agents.live_title')}</header>
      {#if rows.length === 0}
        {#if live.data}<p class="viz-agents__idle" role="status">{t('agents.live_idle')}</p>{/if}
      {:else}
        <div class="viz-agents__room" use:wholeItems>
          <ol class="viz-agents__rows">
            {#each rows as row (row.key)}
              <li class="viz-agents__row" data-agent={row.key}>
                <span class="viz-agents__swatch" style="background:{row.color}" aria-hidden="true"></span>
                <span class="viz-agents__name" title={row.name}>{row.name}</span>
                <span class="oc-gauge viz-agents__bar" data-scale="1" aria-hidden="true"><span class="oc-gauge__bar"><span class="oc-gauge__fill" style="width:{(row.share * 100).toFixed(1)}%;background:{row.color}"></span></span></span>
                <span class="viz-agents__value">{t('agents.rate', { value: formatSi(row.perMinute) })}</span>
              </li>
            {/each}
          </ol>
        </div>
      {/if}
    </section>
  {/if}
  <VizSettings {config} metric={false} range={false} />
</ChartFrame>

<style>
  @layer components {
    :global(.viz-agents) { font-family: var(--font-mono); }

    .viz-agents__head { justify-content: flex-end; }

    .viz-agents__plot { flex: 3 1 0; min-height: 110px; }

    .viz-agents__note { color: var(--oc-text-muted); }

    .viz-agents__live { display: flex; flex: 2 1 0; flex-direction: column; min-height: 0; margin: 0 var(--oc-widget-inset) var(--oc-space-1); box-shadow: 0 -1px 0 var(--oc-line-rule); }

    .viz-agents__livehead { flex: none; padding: var(--oc-space-1) 0; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-agents__room { position: relative; flex: 1 1 0; min-height: 0; overflow: hidden; }

    .viz-agents__rows { margin: 0; padding: 0; list-style: none; }

    .viz-agents__row { display: flex; align-items: center; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-agents__swatch { flex: none; width: var(--oc-space-2); height: var(--oc-space-2); }

    .viz-agents__name { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-agents__bar { flex: 2 1 6ch; --oc-gauge-h: var(--oc-space-1); }

    .viz-agents__value { flex: none; min-width: 8ch; font-variant-numeric: tabular-nums; text-align: right; }

    .viz-agents__idle { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }

    @media (max-width: 700px) {
      .viz-agents__plot { flex: none; height: 11rem; }
      .viz-agents__live { flex: none; }
      .viz-agents__room { flex: none; overflow: visible; }
    }
  }
</style>
