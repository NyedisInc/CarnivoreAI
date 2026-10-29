<script lang="ts">
  import './pack-machines.css';
  import { t } from '../i18n/index.svelte';
  import Check from '../../opscenter/ui/Check.svelte';
  import { packActivity, saveReserve, type ActiveReserve, type PackMachine, type ReserveConfig } from './pack-machines-store.svelte';

  interface Props {
    machine: PackMachine;
    reserve: ActiveReserve & { config: ReserveConfig };
  }
  const { machine, reserve }: Props = $props();

  // svelte-ignore state_referenced_locally
  const start = reserve.config;
  let inCpu = $state(start.in_use.cpu_pct);
  let inMem = $state(start.in_use.mem_pct);
  let awayCpu = $state(start.away.cpu_pct);
  let awayMem = $state(start.away.mem_pct);
  let from = $state(start.schedule.in_use_from);
  let to = $state(start.schedule.in_use_to);
  let days = $state<number[]>([...start.schedule.days]);
  let keys = $state(start.keyboard_rule.enabled);
  let idle = $state(start.keyboard_rule.idle_minutes);

  const DAYS = [0, 1, 2, 3, 4, 5, 6] as const;
  const inRange = (n: number, low: number, high: number): boolean => Number.isInteger(n) && n >= low && n <= high;
  const valid = $derived(
    [inCpu, inMem, awayCpu, awayMem].every((n) => inRange(n, 0, 90)) &&
      /^\d\d:\d\d$/.test(from) && /^\d\d:\d\d$/.test(to) && days.length > 0 && inRange(idle, 1, 240),
  );

  function toggleDay(day: number, on: boolean): void {
    days = on ? [...days, day].sort() : days.filter((d) => d !== day);
  }

  function save(): void {
    if (!valid) return;
    void saveReserve(machine.install_id, {
      in_use: { cpu_pct: inCpu, mem_pct: inMem },
      away: { cpu_pct: awayCpu, mem_pct: awayMem },
      schedule: { in_use_from: from, in_use_to: to, days },
      keyboard_rule: { enabled: keys, idle_minutes: idle },
    } as never);
  }
</script>

<form class="pm-reserve" data-pm="reserve-form" onsubmit={(e) => { e.preventDefault(); save(); }}>
  <h3 class="oc-label">{t('pack.machines.reserve_title')}</h3>
  <p class="pm-note" data-pm="reserve-active">
    {t('pack.machines.reserve_active', { level: t(`pack.machines.level.${reserve.level}`), cpu: reserve.cpu_pct, mem: reserve.mem_pct })}
  </p>
  <div class="pm-grid">
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.level.in_use')} {t('pack.machines.cpu')} %</span>
      <input class="oc-field" type="number" min="0" max="90" bind:value={inCpu} data-reserve="in_use.cpu_pct" /></label>
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.level.in_use')} {t('pack.machines.mem')} %</span>
      <input class="oc-field" type="number" min="0" max="90" bind:value={inMem} data-reserve="in_use.mem_pct" /></label>
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.level.away')} {t('pack.machines.cpu')} %</span>
      <input class="oc-field" type="number" min="0" max="90" bind:value={awayCpu} data-reserve="away.cpu_pct" /></label>
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.level.away')} {t('pack.machines.mem')} %</span>
      <input class="oc-field" type="number" min="0" max="90" bind:value={awayMem} data-reserve="away.mem_pct" /></label>
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.in_use_from')}</span>
      <input class="oc-field" type="time" bind:value={from} data-reserve="schedule.in_use_from" /></label>
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.in_use_to')}</span>
      <input class="oc-field" type="time" bind:value={to} data-reserve="schedule.in_use_to" /></label>
  </div>
  <div class="pm-days" role="group" aria-label={t('pack.machines.days')}>
    {#each DAYS as day}
      <Check label={t(`pack.machines.day.${day}`)} checked={days.includes(day)} data-reserve-day={String(day)}
        onToggle={(next) => toggleDay(day, next)} />
    {/each}
  </div>
  <Check label={t('pack.machines.keyboard_rule')} checked={keys} role="switch" data-reserve="keyboard_rule.enabled"
    onToggle={(next) => (keys = next)} />
  {#if keys}
    <label class="pm-field"><span class="oc-sub">{t('pack.machines.keyboard_idle')}</span>
      <input class="oc-field" type="number" min="1" max="240" bind:value={idle} data-reserve="keyboard_rule.idle_minutes" /></label>
  {/if}
  <div class="pm-actions">
    <button type="submit" class="modal-btn modal-btn-confirm" disabled={!valid || packActivity.busy !== null}
      data-pm="reserve-save">{t('pack.machines.reserve_save')}</button>
  </div>
</form>
