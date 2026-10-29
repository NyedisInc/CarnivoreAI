import { t } from '../i18n/index.svelte';
import { dayClockText } from '../../opscenter/lib/clock';
import { durationText, orderRows, scheduleText, type TimerRow } from './timers';

const HALF_YEAR_MS = 183 * 86_400_000;

function whole(field: string | undefined, min: number, max: number): number | null {
  if (field === undefined || !/^\d+$/.test(field)) return null;
  const n = Number(field);
  return n >= min && n <= max ? n : null;
}

export function pinnedCronAt(cron: string | null | undefined, nowMs: number): number | null {
  const fields = (cron ?? '').trim().split(/\s+/);
  if (fields.length !== 5 || fields[4] !== '*') return null;
  const minute = whole(fields[0], 0, 59);
  const hour = whole(fields[1], 0, 23);
  const day = whole(fields[2], 1, 31);
  const month = whole(fields[3], 1, 12);
  if (minute === null || hour === null || day === null || month === null) return null;
  const year = new Date(nowMs).getFullYear();
  let at = new Date(year, month - 1, day, hour, minute).getTime();
  if (at < nowMs - HALF_YEAR_MS) at = new Date(year + 1, month - 1, day, hour, minute).getTime();
  else if (at > nowMs + HALF_YEAR_MS) at = new Date(year - 1, month - 1, day, hour, minute).getTime();
  return at;
}

function fireMs(row: TimerRow, nowMs: number): number | null {
  const parsed = row.fire_at ? Date.parse(row.fire_at) : NaN;
  if (Number.isFinite(parsed)) return parsed;
  return pinnedCronAt(row.cron, nowMs);
}

export function fireCountdown(row: TimerRow, nowMs: number): string | null {
  const at = fireMs(row, nowMs);
  if (at === null) return null;
  const seconds = (at - nowMs) / 1000;
  return seconds <= 0 ? t('timers.due') : durationText(seconds);
}

export interface TimerLine {
  id: string;
  live: boolean;
  lead: string;
  leadTitle: string;
  prompt: string;
  when: string;
  whenTitle: string;
}

function liveLead(row: TimerRow, at: number | null, nowMs: number): string {
  if (row.kind === 'cron' && pinnedCronAt(row.cron, nowMs) !== null && at !== null) {
    return t('timers.list.once_at', { time: dayClockText(at, nowMs) });
  }
  return scheduleText(row);
}

export function timerLine(row: TimerRow, nowMs: number): TimerLine {
  const live = row.status === 'live';
  const at = fireMs(row, nowMs);
  const prompt = row.prompt ?? t('timers.list.no_prompt');
  const leadTitle = row.cron ?? '';
  if (live) {
    const seconds = at === null ? null : (at - nowMs) / 1000;
    const when = seconds === null
      ? t('timers.list.no_fire_time')
      : seconds <= 0 ? t('timers.due') : t('timers.list.in', { time: durationText(seconds) });
    return { id: row.id, live, lead: liveLead(row, at, nowMs), leadTitle, prompt, when,
      whenTitle: at === null ? '' : dayClockText(at, nowMs) };
  }
  const endedAt = at ?? (Number.isFinite(Date.parse(row.created_at)) ? Date.parse(row.created_at) : null);
  return { id: row.id, live, lead: t(`timers.status.${row.status}`), leadTitle, prompt,
    when: endedAt === null ? t('timers.list.no_fire_time') : dayClockText(endedAt, nowMs),
    whenTitle: scheduleText(row) };
}

export function splitTimers(rows: readonly TimerRow[], nowMs: number): { live: TimerLine[]; history: TimerLine[] } {
  const ordered = orderRows(rows).map((row) => timerLine(row, nowMs));
  return { live: ordered.filter((l) => l.live), history: ordered.filter((l) => !l.live) };
}
