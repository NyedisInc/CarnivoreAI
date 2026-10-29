<script lang="ts">
  import type { SessionTokenUsage, UsageMeter, UsagePanelModel, UsageWindowView } from '../../api';
  import { t } from '../../../lib/i18n/index.svelte';
  import Icon from '../../ui/Icon.svelte';
  import LimitGauge from '../../ui/LimitGauge.svelte';
  import { effortClass } from '../../../lib/effort/effort-level';
  import { statsGroups } from './foot-stats';

  let {
    model,
    payload,
    layout = 'band',
    oncollapse = undefined,
  }: {
    model: UsagePanelModel;
    payload: SessionTokenUsage | null;
    layout?: 'band' | 'tiles';
    oncollapse?: () => void;
  } = $props();

  const groups = $derived(statsGroups(model, payload, Date.now()));

  function fillPct(meter: UsageMeter): number {
    return meter.segments > 0 ? (meter.filled / meter.segments) * 100 : 0;
  }

  function keepTerminalFocus(event: MouseEvent): void {
    event.preventDefault();
  }
</script>

{#snippet gauge(view: UsageWindowView)}
  <span class="oc-tfs-gauge">
    <LimitGauge variant="fill" pct={fillPct(view)} scale={view.scale} paceElapsedPct={view.paceElapsedPct} paceState={view.paceState} meterText={view.meterText} height={6} />
  </span>
{/snippet}

{#snippet bar(meter: UsageMeter, scale: number | null | undefined)}
  <span class="oc-tfs-bar" data-scale={scale ?? ''} role="img" aria-label={meter.meterText}>
    <span class="oc-tfs-bar-fill" style={`width:${fillPct(meter)}%`}></span>
  </span>
{/snippet}

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="oc-tfs" data-usage-state={model.state} data-layout={layout} onmousedown={keepTerminalFocus} onclick={() => oncollapse?.()}>
  {#if model.state === 'ok'}
    {#each groups as group, index (index)}
      <dl class="oc-tfs-group">
        {#each group as cell (cell.key)}
          <div class="oc-tfs-item" data-stat={cell.key}>
            <dt class="oc-tfs-label">{cell.label}</dt>
            <dd class="oc-tfs-value">
              {#if cell.kind === 'context'}
                {@render bar(cell.view, cell.view.scale)}
                {#if cell.view.percentText}<span class="oc-tfs-pct" data-scale={cell.view.scale ?? ''}>{cell.view.percentText}</span>{/if}
                <span class="oc-tfs-num">{cell.view.compactDetail}</span>
              {:else if cell.kind === 'window'}
                {@render gauge(cell.view)}
                <span class="oc-tfs-pct" data-scale={cell.view.scale ?? ''}>{cell.view.percentText}</span>
                <span class="oc-tfs-reset" title={cell.view.resetAria} aria-label={cell.view.resetAria}>
                  <Icon name="recycle" size={11} />
                  <span aria-hidden="true">{cell.view.resetDuration}</span>
                </span>
                {#if cell.resetAt}<span class="oc-tfs-dim">{cell.resetAt}</span>{/if}
              {:else if cell.kind === 'model'}
                <span class="oc-tfs-model" data-tier={cell.row.spans?.[0]?.tier ?? ''}
                  >{cell.row.spans?.[0]?.text}</span>
                {#if cell.effort}
                  <span class="oc-tfs-effort {effortClass(payload?.effort)}" data-word={cell.effort}>{cell.effort}</span>
                {/if}
              {:else if cell.row.parts}
                <span class="oc-tfs-num">{cell.row.parts.lead}<span class="oc-tfs-dim">{cell.row.parts.dim}</span></span>
              {:else}
                <span class="oc-tfs-num oc-tfs-text">{cell.row.text}</span>
              {/if}
            </dd>
          </div>
        {/each}
      </dl>
    {/each}
  {:else}
    <p class="oc-tfs-state" data-usage-state={model.state}>{model.message}</p>
  {/if}
</div>

<style>
  @layer components {
    .oc-tfs {
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      align-content: start;
      column-gap: 14px;
      min-width: 0;
      min-height: 0;
      overflow-y: auto;
      padding: 2px 0;
      font-family: var(--font-mono, monospace);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .oc-tfs[data-layout='band'] {
      display: flex;
      flex-wrap: wrap;
      align-items: stretch;
      overflow: visible;
      padding: 0;
    }

    .oc-tfs[data-layout='tiles'] {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      column-gap: 10px;
      row-gap: 0;
      padding: var(--oc-space-1) 0;
    }

    .oc-tfs-group {
      grid-column: 1 / -1;
      display: grid;
      grid-template-columns: subgrid;
      row-gap: 3px;
      margin: 0;
      padding: 5px var(--oc-space-3);
    }

    .oc-tfs-group + .oc-tfs-group {
      box-shadow: 0 -1px 0 0 var(--oc-line-rule);
    }

    .oc-tfs[data-layout='band'] .oc-tfs-group {
      grid-column: auto;
      grid-template-columns: max-content minmax(0, 1fr);
      flex: 0 0 auto;
      padding: var(--oc-space-1) var(--oc-space-4);
    }

    .oc-tfs[data-layout='band'] .oc-tfs-group + .oc-tfs-group {
      box-shadow: -1px 0 0 0 var(--oc-line-rule);
    }

    .oc-tfs[data-layout='tiles'] .oc-tfs-group {
      display: contents;
    }

    .oc-tfs[data-layout='tiles'] .oc-tfs-item {
      display: flex;
      flex-direction: column;
      gap: 2px;
      padding: var(--oc-space-1) var(--oc-space-2);
      box-shadow: 0 -1px 0 0 var(--oc-line-rule);
    }

    .oc-tfs[data-layout='tiles'] .oc-tfs-bar,
    .oc-tfs[data-layout='tiles'] .oc-tfs-gauge {
      display: none;
    }

    .oc-tfs-item {
      display: contents;
    }

    .oc-tfs-label {
      align-self: center;
      white-space: nowrap;
      font-size: var(--oc-fs-micro, var(--oc-fs-micro));
      letter-spacing: var(--oc-tracking-label, 0.6px);
      text-transform: uppercase;
      color: var(--oc-text-dim);
    }

    .oc-tfs-value {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      margin: 0;
      min-height: 18px;
    }

    .oc-tfs-num {
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }

    .oc-tfs-text {
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }

    .oc-tfs-dim {
      color: var(--oc-text-dim);
      white-space: nowrap;
    }

    .oc-tfs-bar {
      position: relative;
      display: inline-block;
      flex: 0 1 140px;
      min-width: 40px;
      height: 6px;
      border-radius: 3px;
      background: var(--oc-ground-hover);
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
      overflow: hidden;
    }

    .oc-tfs-gauge {
      display: flex;
      flex: 0 1 140px;
      min-width: 40px;
    }

    .oc-tfs-bar-fill {
      position: absolute;
      inset: 0 auto 0 0;
      border-radius: inherit;
      background: var(--oc-text-dim);
    }

    .oc-tfs-bar[data-scale='1'] .oc-tfs-bar-fill { background: var(--oc-green-bright); }

    .oc-tfs-bar[data-scale='2'] .oc-tfs-bar-fill { background: var(--oc-cyan); }

    .oc-tfs-bar[data-scale='3'] .oc-tfs-bar-fill { background: var(--oc-yellow-bright); }

    .oc-tfs-bar[data-scale='4'] .oc-tfs-bar-fill { background: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tfs-bar[data-scale='5'] .oc-tfs-bar-fill { background: var(--oc-coral); }

    .oc-tfs-pct {
      min-width: 4ch;
      text-align: right;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }

    .oc-tfs-pct[data-scale='1'] { color: var(--oc-green-bright); }

    .oc-tfs-pct[data-scale='2'] { color: var(--oc-cyan); }

    .oc-tfs-pct[data-scale='3'] { color: var(--oc-yellow-bright); }

    .oc-tfs-pct[data-scale='4'] { color: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tfs-pct[data-scale='5'] { color: var(--oc-coral); }

    .oc-tfs-reset {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      white-space: nowrap;
      color: var(--oc-text-secondary);
    }

    .oc-tfs-model { color: var(--oc-text-primary); white-space: nowrap; }

    .oc-tfs-model[data-tier='1'] { color: var(--oc-green-bright); }

    .oc-tfs-model[data-tier='2'] { color: var(--oc-cyan); }

    .oc-tfs-model[data-tier='3'] { color: var(--oc-yellow-bright); }

    .oc-tfs-model[data-tier='4'] { color: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral)); }

    .oc-tfs-model[data-tier='5'] { color: var(--oc-coral); }

    .oc-tfs-effort { white-space: nowrap; }

    .oc-tfs-effort:not(:global(.effort-level)) { color: var(--oc-text-dim); }

    .oc-tfs-state {
      grid-column: 1 / -1;
      margin: 0;
      padding: var(--oc-space-2) var(--oc-space-3);
    }

    .oc-tfs-state[data-usage-state='absent'] { color: var(--oc-text-dim); }

    .oc-tfs-state[data-usage-state='unchecked'] { color: var(--oc-yellow); }
  }
</style>
