<script lang="ts">
  /* could not be read */
  import { onMount } from 'svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import StatusLed from '../../lib/StatusLed.svelte';
  import { sessions } from '../api';
  import type { ChartConfig } from '../cells/analytics/types';
  import EmptyState from './EmptyState.svelte';
  import VizSettings from './VizSettings.svelte';
  import { emptyLine } from './empty';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { formatMetric } from './format';
  import { live, watchLive } from './noc-feed.svelte';
  import { acquireStatsFeed, statsFeed } from '../../lib/stats-feed/store.svelte';
  import { vitalsModel } from './noc';
  import { watchVisible } from './visible';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let visible = $state(false);
  onMount(() => watchVisible(root, (value) => { visible = value; }));
  $effect(() => (config.enabled && visible ? watchLive() : undefined));
  $effect(() => (config.enabled && visible ? acquireStatsFeed('1h') : undefined));

  const model = $derived(vitalsModel(live.data, sessions.data, statsFeed('1h')?.data ?? null));
  interface Vital { id: string; label: string; value: string; trend?: string }
  const vitals = $derived.by((): Vital[] => {
    const all: (Vital | null)[] = [
      model.sessions ? { id: 'sessions', label: t('vitals.sessions'), value: String(model.sessions.live) } : null,
      model.tokensPerMinute === null ? null : { id: 'tokens', label: t('vitals.tokens_per_minute'), value: formatMetric(model.tokensPerMinute, 'tokens').text,
        ...(model.trend === 'unknown' ? {} : { trend: model.trend }) },
    ];
    if (tier !== 'tile') {
      all.push(
        model.usdPerHour === null ? null : { id: 'cost', label: t('vitals.usd_per_hour'), value: formatMetric(model.usdPerHour * 1e9, 'nano_usd').text },
        model.cacheHit === null ? null : { id: 'cache', label: t('vitals.cache_hit'), value: formatMetric(model.cacheHit, 'fraction').text },
        model.subagents === null || model.subagents === undefined ? null : { id: 'subagents', label: t('vitals.subagents'), value: String(model.subagents) },
      );
    }
    return all.filter((vital): vital is Vital => vital !== null);
  });
  const states = $derived(model.sessions ? [
    { id: 'working', status: 'working', count: model.sessions.working ?? null },
    { id: 'waiting', status: 'question', count: model.sessions.waiting ?? null },
    { id: 'idle', status: 'idle', count: model.sessions.idle ?? null },
  ].filter((state) => state.count !== null) : []);
</script>

<section bind:this={root} class="viz-vitals viz-vitals--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-vitals__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-vitals__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t('vitals.window')}</span>{/if}</header>
    {#if live.failure && !live.data}<p class="viz-vitals__note" role="alert">{t('viz.item_failed', { message: live.failure })}</p>{/if}
    {#if vitals.length === 0}
      {#if !live.failure}<EmptyState line={emptyLine('vitals')} />{/if}
    {:else}
      <dl class="viz-vitals__grid">
        {#each vitals as vital (vital.id)}
          <div class="viz-vitals__cell" data-vital={vital.id}>
            <dt title={vital.label}>{vital.label}</dt>
            <dd><strong>{vital.value}</strong>{#if vital.trend}<span class="viz-vitals__trend viz-vitals__trend--{vital.trend}">{t(`vitals.trend_${vital.trend}`)}</span>{/if}</dd>
          </div>
        {/each}
      </dl>
    {/if}
    {#if tier === 'full' && states.length}
      <ul class="viz-vitals__states" data-vital="states">
        {#each states as state (state.id)}
          <li><StatusLed status={state.status} unread={false} startupGate={null} statusSource={null} transport={null} /><span>{t(`vitals.state_${state.id}`)}</span><strong>{state.count}</strong></li>
        {/each}
      </ul>
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false} />
</section>

<style>
  @layer components {
    .viz-vitals { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-vitals__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-vitals__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-vitals__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-vitals__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(110px, 1fr)); gap: var(--oc-space-2) var(--oc-space-4); flex: 1; align-content: center; margin: 0; }

    .viz-vitals__cell { min-width: 0; }

    .viz-vitals__cell dt { overflow: hidden; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-vitals__cell dd { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 var(--oc-space-2); min-width: 0; margin: 0; white-space: nowrap; }

    .viz-vitals__cell strong { flex: none; font-size: var(--oc-fs-display); font-weight: 600; letter-spacing: -.04em; line-height: 1.1; font-variant-numeric: tabular-nums; text-overflow: ellipsis; }

    .viz-vitals--tile .viz-vitals__cell strong { font-size: var(--oc-fs-figure); }

    .viz-vitals__trend { flex: none; color: var(--oc-text-muted); }

    .viz-vitals__trend--rising { color: var(--oc-yellow); }

    .viz-vitals__trend--falling { color: var(--oc-cyan); }

    .viz-vitals__states { display: flex; flex-wrap: wrap; gap: var(--oc-space-2) var(--oc-space-5); margin: var(--oc-space-2) 0 0; padding: var(--oc-space-2) 0 0; list-style: none; box-shadow: 0 -1px 0 var(--oc-line-rule); }

    .viz-vitals__states li { display: flex; align-items: center; gap: var(--oc-space-2); color: var(--oc-text-secondary); }

    .viz-vitals__states strong { color: var(--oc-text-primary); font-variant-numeric: tabular-nums; }

    .viz-vitals__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
