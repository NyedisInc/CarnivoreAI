
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import PackMeter from '../pack-machines/PackMeter.svelte';
  import { loadPercent } from '../pack-machines/pack-meter-math';
  import type { RosterComputer } from './roster-model';

  const { c, reserve = true }: { c: RosterComputer; reserve?: boolean } = $props();
  const snap = $derived(c.machine?.snapshot ?? null);
  const fig = (v: number | null | undefined, unit = ''): string => (v == null ? '-' : `${Math.round(v)}${unit}`);
</script>

<div class="pp-meters" data-computer={c.id}>
  {#if snap}
    <PackMeter label={t('pack.machines.cpu')} pct={loadPercent(snap.load.load_1, snap.load.cores)} text={`${fig(snap.load.load_1)}/${fig(snap.load.cores)}`}
      reservePct={snap.reserve.cpu_pct} title={t('pack.meter.cpu_title', { load: fig(snap.load.load_1), cores: fig(snap.load.cores), reserve: snap.reserve.cpu_pct })} />
    <PackMeter label={t('pack.machines.mem')} pct={snap.load.memory_percent ?? null} text={fig(snap.load.memory_percent, '%')} reservePct={snap.reserve.mem_pct}
      title={t('pack.meter.mem_title', { used: fig(snap.load.memory_percent), reserve: snap.reserve.mem_pct })} />
    <PackMeter label={t('pack.machines.disk')} pct={snap.load.disk_percent ?? null} text={fig(snap.load.disk_percent, '%')} title={t('pack.meter.disk_title', { used: fig(snap.load.disk_percent) })} />
    {#if reserve}<p class="pp-reserve" data-pm="reserve-level">{t('pack.machines.reserve')} {t(`pack.machines.level.${snap.reserve.level}`)} {snap.reserve.cpu_pct}% / {snap.reserve.mem_pct}%</p>{/if}
  {:else}
    <PackMeter label={t('pack.machines.cpu')} pct={null} text="-" title={t('pack.machines.cpu')} />
    <PackMeter label={t('pack.machines.mem')} pct={null} text="-" title={t('pack.machines.mem')} />
    <PackMeter label={t('pack.machines.disk')} pct={null} text="-" title={t('pack.machines.disk')} />
  {/if}
</div>
