<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import { releaseSessionUsage, sessionUsage, sessionUsageLabels } from '../../opscenter/api/session-usage.svelte';
  import { primarySessionId } from '../../opscenter/api';
  import { PRIMARY_BIND_EVENT } from '../../opscenter/engine/primary-bind';
  import type { Resource } from '../../opscenter/api/poll.svelte';
  import type { SessionTokenUsage } from '../../opscenter/api/types';
  import LimitGauge from '../../opscenter/ui/LimitGauge.svelte';

  let usageResource = $state<Resource<SessionTokenUsage> | null>(null);

  let primaryId = $state(primarySessionId());

  $effect(() => {
    primaryId = primarySessionId();
    const onBind = (event: Event): void => {
      const id = (event as CustomEvent<{ sessionId?: string }>).detail?.sessionId;
      if (id) primaryId = id;
    };
    globalThis.addEventListener(PRIMARY_BIND_EVENT, onBind);
    return () => globalThis.removeEventListener(PRIMARY_BIND_EVENT, onBind);
  });

  $effect(() => {
    const id = primaryId;
    if (!id) {
      usageResource = null;
      return;
    }
    usageResource = sessionUsage(id);
    return () => releaseSessionUsage(id);
  });

  const usagePayload = $derived(usageResource ? usageResource.data : null);
  const usageModel = $derived(sessionUsageLabels(usagePayload, null));
  const contextMeter = $derived(usageModel.state === 'ok' ? usageModel.context : null);
  const windowMeters = $derived(usageModel.state === 'ok' ? usageModel.windows : []);
  const fiveHourMeter = $derived(windowMeters.find((w) => w.key === 'window:five_hour') ?? null);
  const sevenDayMeter = $derived(windowMeters.find((w) => w.key === 'window:seven_day') ?? null);

  function meterPct(meter: { segments: number; filled: number } | null | undefined): number {
    if (!meter || meter.segments <= 0) return 0;
    return Math.max(0, Math.min(100, (meter.filled / meter.segments) * 100));
  }

  function meterScale(meter: { scale: number | null } | null | undefined): number | '' {
    return meter?.scale ?? '';
  }

  function meterTooltip(meter: { meterText: string } | null | undefined): string {
    return (meter && meter.meterText) || t('drawer.rail.usage_unmeasured');
  }
</script>

<div class="mr-usage" role="group" aria-label={t('drawer.rail.usage')}>
  <span class="mr-usage-item">
    <span class="mr-usage-label">{t('drawer.rail.usage_context_short')}</span>
    <span class="mr-usage-bar" data-usage="context" data-scale={meterScale(contextMeter)} role="img" aria-label={meterTooltip(contextMeter)}>
      <span class="mr-usage-fill" style={`width:${meterPct(contextMeter)}%`}></span>
    </span>
  </span>
  <span class="mr-usage-item">
    <span class="mr-usage-label">{t('drawer.rail.usage_5h_short')}</span>
    <LimitGauge variant="fill" class="mr-usage-bar" data-usage="5h"
      pct={meterPct(fiveHourMeter)} scale={fiveHourMeter?.scale ?? null} paceElapsedPct={fiveHourMeter?.paceElapsedPct ?? null} paceState={fiveHourMeter?.paceState ?? null}
      meterText={meterTooltip(fiveHourMeter)} height={3} />
  </span>
  <span class="mr-usage-item">
    <span class="mr-usage-label">{t('drawer.rail.usage_7d_short')}</span>
    <LimitGauge variant="fill" class="mr-usage-bar" data-usage="7d"
      pct={meterPct(sevenDayMeter)} scale={sevenDayMeter?.scale ?? null} paceElapsedPct={sevenDayMeter?.paceElapsedPct ?? null} paceState={sevenDayMeter?.paceState ?? null}
      meterText={meterTooltip(sevenDayMeter)} height={3} />
  </span>
</div>

<style>
  @layer components {
    .mr-usage {
      flex: 0 0 auto;
      display: flex;
      flex-direction: column;
      align-items: stretch;
      gap: var(--oc-space-2);
      width: 100%;
      padding: var(--oc-space-2) 6px var(--oc-space-1);
      box-sizing: border-box;
    }

    .mr-usage-item {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
    }

    .mr-usage-label {
      flex: 0 0 auto;
      width: 14px;
      font-size: 8px;
      line-height: 1;
      letter-spacing: 0.02em;
      color: var(--oc-text-dim);
      text-align: right;
    }

    .mr-usage-bar {
      display: block;
      flex: 1 1 auto;
      min-width: 0;
      height: 3px;
      border-radius: 1.5px;
      background: var(--oc-line-panel);
      overflow: hidden;
    }

    :global(.mr-usage-bar .oc-gauge__bar) {
      background: var(--oc-line-panel);
      box-shadow: none;
    }

    .mr-usage-fill {
      display: block;
      height: 100%;
      background: var(--oc-text-dim);
      transition: width 0.2s ease, background 0.2s ease;
    }

    .mr-usage-bar[data-scale='1'] .mr-usage-fill {
      background: var(--oc-green-bright);
    }
    .mr-usage-bar[data-scale='2'] .mr-usage-fill {
      background: var(--oc-cyan);
    }
    .mr-usage-bar[data-scale='3'] .mr-usage-fill {
      background: var(--oc-yellow-bright);
    }
    .mr-usage-bar[data-scale='4'] .mr-usage-fill {
      background: color-mix(in oklab, var(--oc-yellow-bright) 55%, var(--oc-coral));
    }
    .mr-usage-bar[data-scale='5'] .mr-usage-fill {
      background: var(--oc-coral);
    }
  }
</style>
