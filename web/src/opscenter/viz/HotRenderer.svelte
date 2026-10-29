<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import { openSession, sessions } from '../api';
  import type { ChartConfig } from '../cells/analytics/types';
  import VizSettings from './VizSettings.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { formatMetric } from './format';
  import { hotRows, hotTag, liveSessionFor } from './noc';
  import { derivedDisplayName } from '../../lib/sessions/session-label';
  import { live, watchLive } from './noc-feed.svelte';
  import { watchVisible } from './visible';
  import { wholeItems } from './whole-items';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let visible = $state(false);
  onMount(() => watchVisible(root, (value) => { visible = value; }));
  $effect(() => (config.enabled && visible ? watchLive() : undefined));

  const rows = $derived.by(() => {
    const list = hotRows(live.data);
    return list.map((row) => {
      const target = liveSessionFor(row.conversationId, sessions.data);
      return { row, target, tag: hotTag(row, list, target ? derivedDisplayName(target.tmux_session) : null) };
    });
  });
</script>

<section bind:this={root} class="viz-hot viz-hot--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-hot__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-hot__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t('hot.window')}</span>{/if}</header>
    {#if live.failure && !live.data}<p class="viz-hot__note" role="alert">{t('viz.item_failed', { message: live.failure })}</p>{/if}
    {#if rows.length === 0 && !live.failure}
      {#if live.data}<EmptyState line={emptyLine('live')} />{/if}
    {:else}
      <ol class="viz-hot__rows" use:wholeItems>
        {#each rows as { row, target, tag } (row.key)}
          <li class="viz-hot__row">
            {#if target}
              <a class="viz-hot__name viz-hot__open" href="#session" title={t('hot.open')} onclick={(event) => { event.preventDefault(); openSession(target.session.id, target.tmux_session); }}>{row.project ?? t('viz.no_data')}{#if tag}<span class="viz-hot__tag">{tag}</span>{/if}</a>
            {:else}
              <span class="viz-hot__name" title={row.project ?? ''}>{row.project ?? t('viz.no_data')}{#if tag}<span class="viz-hot__tag">{tag}</span>{/if}</span>
            {/if}
            {#if tier !== 'tile'}
              <span class="viz-hot__model" title={row.model ?? ''}>{row.model ?? t('viz.no_data')}</span>
              <span class="oc-gauge viz-hot__bar" data-scale="2" aria-hidden="true"><span class="oc-gauge__bar"><span class="oc-gauge__fill" style="width:{(row.share * 100).toFixed(1)}%"></span></span></span>
            {/if}
            {#if tier === 'full'}<span class="viz-hot__provider">{row.provider}</span>{/if}
            <span class="viz-hot__value">{formatMetric(row.tokens, 'tokens').text}</span>
            {#if tier === 'full'}<span class="viz-hot__cost">{row.costUsd === null ? t('viz.no_data') : formatMetric(row.costUsd * 1e9, 'nano_usd').text}</span>{/if}
          </li>
        {/each}
      </ol>
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false} />
</section>

<style>
  @layer components {
    .viz-hot { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-hot__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-hot__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-hot__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-hot__rows { flex: 1; min-height: 0; margin: 0; padding: 0; overflow: hidden; list-style: none; }

    .viz-hot__row { display: flex; align-items: center; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-hot__name { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-hot__open { color: var(--oc-cyan); text-decoration: none; }

    .viz-hot__open:hover { text-decoration: underline; }

    .viz-hot__tag { margin-left: var(--oc-space-1); color: var(--oc-text-dim); }

    .viz-hot__model { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-muted); text-overflow: ellipsis; white-space: nowrap; }

    .viz-hot__bar { flex: 2 1 6ch; --oc-gauge-h: var(--oc-space-2); }

    .viz-hot__provider { flex: none; min-width: 6ch; color: var(--oc-text-muted); }

    .viz-hot__value, .viz-hot__cost { flex: none; min-width: 6ch; font-variant-numeric: tabular-nums; text-align: right; }

    .viz-hot__cost { color: var(--oc-text-secondary); }

    .viz-hot__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
