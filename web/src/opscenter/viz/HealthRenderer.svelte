<script lang="ts">
  import { analytics } from '../cells/analytics/state.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import EmptyState from './EmptyState.svelte';
  import VizSettings from './VizSettings.svelte';
  import { emptyLine } from './empty';
  import { formatDuration, formatSi } from './format';
  import { healthModel, scaleBytes, type CoverageInput } from './health';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();

  const model = $derived(healthModel(analytics.coverage as CoverageInput | null, analytics.tickAt / 1000));
  interface Fact { id: string; label: string; value: string; note?: string; tone?: string }
  const age = (value: number | null): string | undefined => (value === null ? undefined : t('health.ago', { value: formatDuration(value) }));
  const facts = $derived.by((): Fact[] => {
    const scaled = model.dbBytes === null ? null : scaleBytes(model.dbBytes);
    const all: (Fact | null)[] = [
      model.state === null ? null : { id: 'collector', label: t('health.collector'), value: t(`health.state_${model.state}`), note: age(model.passAgeSeconds), tone: model.tone },
      model.pendingSources === null ? null : {
        id: 'backlog', label: t('health.backlog_label'),
        value: model.pendingSources === 0 ? t('health.backlog_clear')
          : model.knownSources === null ? formatSi(model.pendingSources)
          : t('health.backlog', { pending: formatSi(model.pendingSources), known: formatSi(model.knownSources) }),
        note: tier === 'tile' || model.replaying === null ? undefined : t(model.replaying ? 'health.replay_running' : 'health.replay_idle'),
      },
    ];
    if (tier !== 'tile') {
      all.push(
        model.freshnessSeconds === null ? null : { id: 'freshness', label: t('health.freshness'), value: age(model.freshnessSeconds) as string },
        model.missingSources === null ? null : { id: 'missing', label: t('health.missing'), value: formatSi(model.missingSources) },
        scaled === null ? null : { id: 'size', label: t('health.size'), value: t(`health.${scaled.unit}`, { value: scaled.value }) },
      );
    }
    if (tier === 'full') {
      all.push(
        model.qualityRows === null ? null : { id: 'quality', label: t('health.quality'), value: formatSi(model.qualityRows) },
        model.unknownCostRows === null ? null : { id: 'unpriced', label: t('health.unpriced'), value: formatSi(model.unknownCostRows) },
      );
    }
    return all.filter((fact): fact is Fact => fact !== null);
  });
</script>

<section class="viz-health viz-health--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-health__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-health__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile'}<span>{t('health.window')}</span>{/if}</header>
    {#if facts.length === 0}
      <EmptyState line={emptyLine('chart')} />
    {:else}
      <dl class="viz-health__grid">
        {#each facts as fact (fact.id)}
          <div class="viz-health__cell" data-health={fact.id}><dt>{fact.label}</dt>
            <dd><strong class={fact.tone ? `viz-health__state viz-health__state--${fact.tone}` : undefined}>{fact.value}</strong>{#if fact.note} <span>{fact.note}</span>{/if}</dd></div>
        {/each}
      </dl>
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false} />
</section>

<style>
  @layer components {
    .viz-health { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-health__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-health__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-health__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-health__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(14ch, 1fr)); gap: var(--oc-space-2) var(--oc-space-3); flex: 1; align-content: start; min-height: 0; margin: var(--oc-space-2) 0 0; overflow: hidden; }

    .viz-health__cell { min-width: 0; }

    .viz-health__cell dt { overflow: hidden; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-health__cell dd { display: flex; flex-direction: column; min-width: 0; margin: 0; font-variant-numeric: tabular-nums; }

    .viz-health__cell dd span { color: var(--oc-text-muted); }

    .viz-health__state--ok { color: var(--oc-green); }

    .viz-health__state--warn { color: var(--oc-yellow); }

    .viz-health__state--bad { color: var(--oc-coral); }

    .viz-health__state--unknown { color: var(--oc-text-muted); }

    .viz-health__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
