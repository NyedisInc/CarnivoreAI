<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import VizSettings from './VizSettings.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { mergeEvents } from './noc';
  import { ticker, watchTicker } from './noc-feed.svelte';
  import { watchVisible } from './visible';
  import { wholeItems } from './whole-items';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let visible = $state(false);
  onMount(() => watchVisible(root, (value) => { visible = value; }));
  $effect(() => (config.enabled && visible ? watchTicker() : undefined));

  const rows = $derived(ticker.data ? mergeEvents(ticker.data.log, ticker.data.marks) : []);

  function stamp(at: number): string {
    const date = new Date(at * 1000);
    const clock = date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false });
    return tier === 'full' ? `${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${clock}` : clock;
  }
</script>

<section bind:this={root} class="viz-events viz-events--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-events__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-events__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t('events.window')}</span>{/if}</header>
    {#if ticker.failure && !ticker.data}<p class="viz-events__note" role="alert">{t('viz.item_failed', { message: ticker.failure })}</p>{/if}
    {#if rows.length === 0 && !ticker.failure}
      {#if ticker.data}<EmptyState line={emptyLine('events')} />{/if}
    {:else}
      <ol class="viz-events__rows" use:wholeItems={{ enabled: tier === 'tile' }}>
        {#each rows as row (row.key)}
          <li class="viz-events__row">
            {#if tier !== 'tile'}<time class="viz-events__time" datetime={new Date(row.at * 1000).toISOString()}>{stamp(row.at)}</time>{/if}
            <span class="viz-events__kind">{t(row.kindKey)}</span>
            <span class="viz-events__subject" title={row.subject}>{row.subject}</span>
          </li>
        {/each}
      </ol>
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false} />
</section>

<style>
  @layer components {
    .viz-events { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-events__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-events__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-events__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-events__rows { flex: 1; min-height: 0; margin: 0; padding: 0; overflow-y: auto; list-style: none; }

    .viz-events--tile .viz-events__rows { overflow-y: hidden; }

    .viz-events__row { display: flex; align-items: baseline; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-events__time { flex: none; color: var(--oc-text-dim); font-variant-numeric: tabular-nums; }

    .viz-events__kind { flex: none; color: var(--oc-orange); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-events__subject { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-events__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
