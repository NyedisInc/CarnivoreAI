import { t } from '../i18n/index.svelte';
import { timerChip } from '../timers/timers';

export interface SleepHoldFields {
  sleep_hold?: { reasons: string[]; text: string } | null;
  sleep_verdict?: {
    code: string;
    idle_since?: string | null;
    threshold_minutes?: number | null;
    reasons?: string[];
    detail?: string | null;
  } | null;
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

export function sleepVerdictLine(row: SleepHoldFields | null | undefined, nowMs: number): string | null {
  const v = row?.sleep_verdict;
  if (!v || v.code === 'not_agent') return null;
  let why: string;
  if (v.code === 'idle_waiting' || v.code === 'due') {
    const since = v.idle_since ? Date.parse(v.idle_since) : NaN;
    const idle = Number.isFinite(since) ? Math.max(0, Math.floor((nowMs - since) / 60000)) : 0;
    why = t(`auto_sleep.verdict.${v.code}`, { idle, limit: v.threshold_minutes ?? 0 });
  } else if (v.code === 'work_running') {
    why = sleepHoldParts({ ...row, sleep_hold: { reasons: v.reasons ?? [], text: '' } }, nowMs) ?? t('auto_sleep.verdict.work_running');
  } else {
    why = t(`auto_sleep.verdict.${v.code}`, { detail: v.detail ?? '' });
  }
  return t('auto_sleep.verdict.prefix', { why });
}
