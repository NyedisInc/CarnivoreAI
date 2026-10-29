<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import { formatMetric } from './format';
  import type { Alarm } from './tripwire-model';

  let { alarm, unit }: { alarm: Alarm; unit: string } = $props();
  const wire = $derived(alarm.wire);
  const reading = $derived(wire ? t('tripwire.reading', {
    value: formatMetric(wire.last_value, unit).text, comparator: wire.comparator, threshold: formatMetric(wire.threshold, unit).text,
  }) : '');
</script>

{#if alarm.state === 'firing'}
  <div class="alarm-strip alarm-strip--firing" role="status" data-alarm="firing"><strong>{t('tripwire.tripped')}</strong><span>{reading}</span></div>
{:else if alarm.state === 'unknown'}
  <div class="alarm-strip" role="status" data-alarm="unknown"><span>{t('tripwire.no_data')}</span></div>
{/if}

<style>
  @layer components {
    .alarm-strip { display: flex; align-items: baseline; justify-content: space-between; gap: var(--oc-space-2); min-width: 0; padding: var(--oc-space-1) var(--oc-space-3); color: var(--oc-text-muted); font: var(--oc-fs-micro) var(--font-mono); letter-spacing: .08em; text-transform: uppercase; box-shadow: 0 1px 0 var(--oc-line-rule); }

    .alarm-strip--firing { color: var(--oc-coral); }

    .alarm-strip strong { font-weight: 600; }

    .alarm-strip span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-variant-numeric: tabular-nums; }
  }
</style>
