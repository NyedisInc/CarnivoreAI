<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import { onMount } from 'svelte';
  import VizSettings from './VizSettings.svelte';
  import { authFetch } from '../api/auth.svelte';
  import { analytics } from '../cells/analytics/state.svelte';
  import { annotations } from '../cells/analytics/api';
  import type { ChartConfig } from '../cells/analytics/types';
  import { changeAnalyticsConfig } from '../layout-editor/editor.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { formatMetric } from './format';
  import { insightRead } from './insight-query.svelte';
  import { IMPACT_DAYS, IMPACT_MARKER_SPAN_MS, IMPACT_METRICS, impactDays, impactMetric, impactModel, impactPath, pickMarker, type ImpactPayload } from './impact';
  import { watchVisible } from './visible';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  let root: HTMLElement;
  let visible = $state(false);
  onMount(() => watchVisible(root, (value) => { visible = value; }));
  const metric = $derived(impactMetric(config));
  const days = $derived(impactDays(config));
  const chosen = $derived(typeof config.options?.annotation_id === 'string' ? config.options.annotation_id : '');

  const markers = insightRead(() => {
    const to = analytics.tickAt;
    return { key: config.enabled ? `markers:${to}` : null, fetch: (signal: AbortSignal) => annotations(new Date(to - IMPACT_MARKER_SPAN_MS).toISOString(), new Date(to + 60_000).toISOString(), signal) };
  }, () => visible);
  const markerId = $derived(pickMarker(markers.data ?? [], chosen, analytics.tickAt / 1000));
  const read = insightRead<ImpactPayload>(() => {
    const path = markerId ? impactPath(markerId, metric, days) : null;
    return { key: config.enabled && path ? `${path}:${analytics.tickAt}` : null, fetch: (signal) => authFetch<ImpactPayload>(path as string, { signal }) };
  }, () => visible);
  const model = $derived(impactModel(read.data));
  const unit = $derived(read.data?.unit ?? '');
  const money = (value: number | null): string => formatMetric(value, unit).text;
  const percent = $derived(model?.change == null ? '' : formatMetric(model.change, 'fraction').text);
  const label = $derived(read.data?.annotation.label ?? '');
  function edit(patch: Record<string, unknown>): void {
    changeAnalyticsConfig({ ...config, options: { ...config.options, ...patch } });
  }
</script>

<section bind:this={root} class="viz-impact viz-impact--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-impact__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-impact__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t('impact.window', { days })}</span>{/if}</header>
    {#if read.failure || markers.failure}<p class="viz-impact__note" role="alert">{t('viz.item_failed', { message: read.failure || markers.failure })}</p>{/if}
    {#if markers.data && !markerId}
      <p class="viz-impact__note">{t('impact.no_marker')}</p>
    {:else if model}
      <p class="viz-impact__marker" title={label}>{label}</p>
      <p class="viz-impact__verdict viz-impact__verdict--{model.verdict}" data-impact-verdict={model.verdict}>{t(`impact.verdict_${model.verdict}`)}{#if model.verdict !== 'insufficient' && percent} <strong>{percent}</strong>{/if}</p>
      {#if tier !== 'tile'}
        <dl class="viz-impact__grid">
          <div><dt>{t('impact.before')}</dt><dd>{money(model.before)}{#if tier === 'full'} <span>{t('impact.n', { count: model.nBefore })}</span>{/if}</dd></div>
          <div><dt>{t('impact.after')}</dt><dd>{money(model.after)}{#if tier === 'full'} <span>{t('impact.n', { count: model.nAfter })}</span>{/if}</dd></div>
          {#if model.low !== null && model.high !== null}<div><dt>{t('impact.interval')}</dt><dd>{money(model.low)} {t('impact.to')} {money(model.high)}</dd></div>{/if}
        </dl>
        {#if model.mixShifted && model.mover}<p class="viz-impact__flag">{t('impact.mix_shift', { model: model.mover.model, before: formatMetric(model.mover.before, 'fraction').text, after: formatMetric(model.mover.after, 'fraction').text })}</p>{/if}
        {#if model.partial}<p class="viz-impact__note">{t('impact.partial')}</p>{/if}
      {/if}
      {#if tier === 'full'}<p class="viz-impact__note">{t('impact.caveat')}</p>{/if}
    {:else if !read.failure && read.data}
      <EmptyState line={emptyLine('conversations')} />
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false}>
    <label>{t('impact.marker')} <select value={chosen} onchange={(event) => edit({ annotation_id: event.currentTarget.value })}>
      <option value="">{t('impact.marker_newest')}</option>
      {#each markers.data ?? [] as marker (marker.id)}<option value={marker.id}>{marker.label}</option>{/each}
    </select></label>
    <label>{t('viz.measure')} <select value={metric} onchange={(event) => edit({ metric: event.currentTarget.value })}>
      {#each IMPACT_METRICS as item (item)}<option value={item}>{t(`impact.metric_${item}`)}</option>{/each}
    </select></label>
    <label>{t('impact.days')} <select value={String(days)} onchange={(event) => edit({ days: Number(event.currentTarget.value) })}>
      {#each IMPACT_DAYS as item (item)}<option value={String(item)}>{item}</option>{/each}
    </select></label>
  </VizSettings>
</section>

<style>
  @layer components {
    .viz-impact { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-impact__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-impact__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-impact__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-impact__marker { margin: var(--oc-space-1) 0 0; overflow: hidden; color: var(--oc-text-secondary); text-overflow: ellipsis; white-space: nowrap; }

    .viz-impact__verdict { margin: var(--oc-space-1) 0; color: var(--oc-text-primary); }

    .viz-impact__verdict strong { margin-inline-start: var(--oc-space-2); font-size: var(--oc-fs-body); font-variant-numeric: tabular-nums; }

    .viz-impact__verdict--insufficient, .viz-impact__verdict--no_clear_change { color: var(--oc-text-muted); }

    .viz-impact__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(9ch, 1fr)); gap: var(--oc-space-1) var(--oc-space-3); margin: 0; }

    .viz-impact__grid dt { color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-impact__grid dd { margin: 0; font-variant-numeric: tabular-nums; }

    .viz-impact__grid dd span { margin-inline-start: var(--oc-space-1); color: var(--oc-text-muted); }

    .viz-impact__flag { margin: var(--oc-space-1) 0 0; color: var(--oc-yellow); }

    .viz-impact__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
