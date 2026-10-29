import { t } from '../i18n/index.svelte';
import { timerChip } from '../timers/timers';

export interface SleepHoldFields {
  sleep_hold?: { reasons: string[]; text: string } | null;
  timers_live?: number | null;
  timers_next_fire_at?: string | null;
  subagents_running?: number | null;
  background_open?: number | null;
}

function atLeastOne(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 1;
}

export function sleepHoldParts(row: SleepHoldFields | null | undefined, nowMs: number): string | null {
  const reasons = row?.sleep_hold?.reasons ?? [];
  if (!row || reasons.length === 0) return null;
  const parts: string[] = [];
  for (const reason of reasons) {
    if (reason === 'timers') {
      const chip = timerChip(row, nowMs);
      parts.push(chip ? chip.title : t('timers.badge.title_no_time', { count: atLeastOne(row.timers_live) }));
    } else if (reason === 'subagents') {
      parts.push(t('auto_sleep.hold.subagents', { count: atLeastOne(row.subagents_running) }));
    } else if (reason === 'background') {
      parts.push(t('auto_sleep.hold.background', { count: atLeastOne(row.background_open) }));
    } else if (reason === 'parked') {
      parts.push(t('auto_sleep.hold.parked'));
    } else if (reason === 'unmeasured') {
      parts.push(t('auto_sleep.hold.unmeasured'));
    }
  }
  return parts.length ? parts.join('; ') : null;
}

export function sleepHoldText(row: SleepHoldFields | null | undefined, nowMs: number): string | null {
  const parts = sleepHoldParts(row, nowMs);
  return parts ? t('auto_sleep.hold.prefix', { parts }) : null;
}
