<script lang="ts">
  import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';
  import { providerMark } from '../sessions/agent-marks';
  import { credentialLabel } from '../ledger/ledger-model';
  import { t } from '../i18n/index.svelte';
  import type { GlanceWindowFigure, ProviderGlance } from './glance-tiles';

  let { data, onopen }: { data: ProviderGlance; onopen: () => void } = $props();

  const MARK_PX = 10;
  const BAR_PX = 3;

  const mark = $derived(providerMark(data.provider, MARK_PX));
  const usable = $derived(data.credentialState === 'ok');
  const rows = $derived(
    [
      { key: 'short', label: t('ledger.glance.short'), figure: data.short },
      { key: 'long', label: t('ledger.glance.long'), figure: data.long },
    ].filter((row): row is { key: string; label: string; figure: GlanceWindowFigure } => row.figure !== null),
  );

  function meterText(label: string, figure: GlanceWindowFigure): string {
    return t(figure.amber ? 'ledger.glance.meter_ahead' : 'ledger.glance.meter', { label, percent: Math.round(figure.usedPct) });
  }

  const status = $derived(
    !usable
      ? credentialLabel(data.credentialState, t)
      : rows.length === 0
        ? t('ledger.glance.no_figures')
        : rows.map((row) => `${row.label} ${t('ledger.glance.percent', { percent: Math.round(row.figure.usedPct) })}`).join(', '),
  );
  const whole = $derived(t('ledger.glance.tile_title', { title: data.title, account: data.accountName, status }));
</script>

<button
  type="button"
  class="pgl"
  data-provider={data.provider}
  data-account={data.accountId}
  title={whole}
  aria-label={t('ledger.glance.open', { tile: whole })}
  onclick={onopen}
>
  <span class="pgl-head">
    <span class="pgl-mark" data-provider-mark={mark.key} aria-hidden="true">{@html mark.svg}</span>
    <span class="pgl-name" data-account-label>{data.accountLabel}</span>
  </span>
  {#if !usable || rows.length === 0}
    <span class="pgl-note">{!usable ? credentialLabel(data.credentialState, t) : t('ledger.glance.no_figures')}</span>
  {:else}
    <span class="pgl-bars">
      {#each rows as row (row.key)}
        <LimitGauge
          variant="fill"
          pct={row.figure.usedPct}
          scale={row.figure.step}
          paceElapsedPct={row.figure.pacerPct}
          meterText={meterText(row.label, row.figure)}
          height={BAR_PX}
          data-window={row.key}
          data-amber={row.figure.amber ? '1' : undefined}
        />
      {/each}
    </span>
  {/if}
</button>

<style>
  @layer components {
    .pgl {
      display: grid;
      align-content: start;
      gap: var(--oc-space-1);
      box-sizing: border-box;
      width: 100%;
      height: 100%;
      min-width: 0;
      padding: 3px 5px;
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      color: var(--oc-text-secondary);
      font: inherit;
      text-align: left;
      cursor: pointer;
      overflow: hidden;
    }

    .pgl-head {
      display: flex;
      align-items: center;
      gap: 3px;
      min-width: 0;
      height: 12px;
    }

    .pgl-mark {
      display: inline-flex;
      flex: none;
    }

    .pgl-name {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: 12px;
      color: var(--oc-text-primary);
    }

    .pgl-bars {
      display: grid;
      gap: var(--oc-space-1);
      padding: 0 1px;
    }

    .pgl-note {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: 9px;
      line-height: 11px;
      color: var(--oc-text-muted);
    }
  }
</style>
