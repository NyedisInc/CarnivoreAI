<script lang="ts">
  import EmptyState from './EmptyState.svelte';
  import { framedTitle } from '../shell/frame-header.svelte';
  import { emptyLine } from './empty';
  import { scaleStep } from '../../../../client/js/labels/usage-panel.js';
  import StatusLed from '../../lib/StatusLed.svelte';
  import SessionFace from '../../lib/sessions/SessionFace.svelte';
  import { openSession, sessions } from '../api';
  import { transportFor } from '../cells/terminal-live/connection.svelte';
  import type { ChartConfig } from '../cells/analytics/types';
  import LimitGauge from '../ui/LimitGauge.svelte';
  import VizSettings from './VizSettings.svelte';
  import { t } from '../../lib/i18n/index.svelte';
  import type { Tier } from './density';
  import { fleetModel, type FleetState } from './fleet';
  import { wholeItems } from './whole-items';

  let { config, tier }: { config: ChartConfig; tier: Tier } = $props();
  const framing = framedTitle();
  const model = $derived(fleetModel(sessions.data));
  const SUMMARY: { state: FleetState; status: string | null }[] = [
    { state: 'working', status: 'working' }, { state: 'waiting', status: 'question' }, { state: 'idle', status: 'idle' }, { state: 'unknown', status: 'unknown' },
  ];
</script>

<section class="viz-fleet viz-fleet--{tier}" aria-label={config.title}>
  {#if !config.enabled}
    <p class="viz-fleet__note">{t('analytics.chart_disabled')}</p>
  {:else}
    <header class="viz-fleet__head">{#if !framing.on}<strong title={config.title}>{config.title}</strong>{/if}{#if tier !== 'tile' && model.total !== null}<span>{t('fleet.count', { count: model.total })}</span>{/if}</header>
    {#if tier === 'tile' && model.total === null}
      <EmptyState line={emptyLine('live')} />
    {:else if tier === 'tile'}
      <ul class="viz-fleet__summary" data-fleet="summary" use:wholeItems>
        {#each SUMMARY as item (item.state)}
          <li title={t(`fleet.state_${item.state}`)}><StatusLed status={item.status} unread={false} startupGate={null} statusSource={null} transport={null} /><strong>{model.counts[item.state]}</strong><span>{t(`fleet.state_${item.state}`)}</span></li>
        {/each}
      </ul>
    {:else if model.rows.length === 0}
      {#if model.total !== null}<EmptyState line={emptyLine('live')} />{/if}
    {:else}
      <ol class="viz-fleet__rack" data-fleet="rack">
        {#each model.rows as row (row.key)}
          {@const step = row.contextPct === null ? null : scaleStep(row.contextPct)}
          <li class="viz-fleet__row" data-fleet-row={row.sessionId}>
            <SessionFace facts={{ ...row.led, transport: transportFor(row.sessionId) }} />
            <a class="viz-fleet__name" href="#session" title={t('fleet.open')} onclick={(event) => { event.preventDefault(); openSession(row.sessionId, row.tmuxSession); }}>{row.name}</a>
            <span class="viz-fleet__project" title={row.project ?? ''}>{row.project ?? ''}</span>
            {#if tier === 'full'}<span class="viz-fleet__model" title={row.model ?? ''}>{row.model ?? ''}</span>{/if}
            <span class="viz-fleet__context">
              {#if row.contextPct !== null && step !== null}
                <LimitGauge variant="fill" pct={row.contextPct} scale={step} meterText={t('sidebar.row.context.label', { percent: Math.round(row.contextPct) })} height={4} />
              {/if}
            </span>
            <span class="viz-fleet__subs" title={t('fleet.subagents')}>{row.subagents === null ? '' : t('fleet.subs', { count: row.subagents })}</span>
          </li>
        {/each}
      </ol>
    {/if}
  {/if}
  <VizSettings {config} metric={false} range={false} />
</section>

<style>
  @layer components {
    .viz-fleet { display: flex; flex-direction: column; min-width: 0; height: 100%; overflow: hidden; padding: var(--oc-space-2) var(--oc-space-3); box-sizing: border-box; color: var(--oc-text-primary); font-family: var(--font-mono); font-size: var(--oc-fs-label); }

    .viz-fleet__head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding-bottom: var(--oc-space-1); box-shadow: 0 1px 0 var(--oc-line-rule); }

    .viz-fleet__head strong { overflow: hidden; color: var(--oc-text-secondary); font-size: var(--oc-fs-micro); font-weight: 600; letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-fleet__head span { flex: none; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-transform: uppercase; }

    .viz-fleet__summary { min-height: 0; overflow: hidden; display: grid; grid-template-columns: repeat(auto-fit, minmax(7.5rem, 1fr)); flex: 1; align-content: safe center; gap: var(--oc-space-2) var(--oc-space-4); margin: 0; padding: 0; list-style: none; }

    .viz-fleet__summary li { display: flex; align-items: center; gap: var(--oc-space-2); min-width: 0; color: var(--oc-text-secondary); }

    .viz-fleet__summary strong { color: var(--oc-text-primary); font-size: var(--oc-fs-figure); font-variant-numeric: tabular-nums; }

    .viz-fleet__summary span { overflow: hidden; color: var(--oc-text-muted); font-size: var(--oc-fs-micro); letter-spacing: .08em; text-overflow: ellipsis; text-transform: uppercase; white-space: nowrap; }

    .viz-fleet__rack { flex: 1; min-height: 0; margin: 0; padding: 0; overflow: auto; list-style: none; }

    .viz-fleet__row { display: flex; align-items: center; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) 0; box-shadow: 0 1px 0 var(--oc-line-faint); }

    .viz-fleet__name { flex: 2 1 10ch; min-width: 0; overflow: hidden; color: var(--oc-cyan); text-decoration: none; text-overflow: ellipsis; white-space: nowrap; }

    .viz-fleet__name:hover { text-decoration: underline; }

    .viz-fleet__project, .viz-fleet__model { flex: 1 1 8ch; min-width: 0; overflow: hidden; color: var(--oc-text-muted); text-overflow: ellipsis; white-space: nowrap; }

    .viz-fleet__context { flex: 0 0 calc(var(--oc-space-6) + var(--oc-space-4)); }

    .viz-fleet__subs { flex: none; min-width: 5ch; color: var(--oc-text-secondary); font-variant-numeric: tabular-nums; text-align: right; }

    .viz-fleet__note { margin: var(--oc-space-1) 0; color: var(--oc-text-muted); }
  }
</style>
