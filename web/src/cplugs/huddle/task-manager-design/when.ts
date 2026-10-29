import { t } from '../../sdk';
import type { Task } from './model';

export interface TaskClock {
  readonly nowSec: number;
  readonly zone: string;
}

const OWNER = 'owner';
const MINUTE_S = 60;
const HOUR_S = 3600;
const AGE_HOURS_SHOWN = 3;

interface Parts { year: number; month: number; day: number; hour: number; minute: number }

const FORMATTERS = new Map<string, Intl.DateTimeFormat>();

function partsIn(atSec: number, zone: string): Parts {
  let format = FORMATTERS.get(zone);
  if (!format) {
    try {
      format = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' });
    } catch (error) {
      if (!(error instanceof RangeError)) throw error;
      format = new Intl.DateTimeFormat('en-US', { timeZone: 'UTC', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', hourCycle: 'h23' });
    }
    FORMATTERS.set(zone, format);
  }
  const out: Record<string, number> = {};
  for (const part of format.formatToParts(new Date(atSec * 1000))) if (part.type !== 'literal') out[part.type] = Number(part.value);
  return { year: out.year ?? 0, month: out.month ?? 1, day: out.day ?? 1, hour: (out.hour ?? 0) % 24, minute: out.minute ?? 0 };
}

function sameDay(a: Parts, b: Parts): boolean {
  return a.year === b.year && a.month === b.month && a.day === b.day;
}

function clockOf(p: Parts): string {
  const hour = p.hour % 12 || 12;
  return t(p.hour < 12 ? 'cplug.huddle.tm.time_am' : 'cplug.huddle.tm.time_pm', { h: hour, mm: String(p.minute).padStart(2, '0') });
}

function dateOf(p: Parts, now: Parts): string {
  const month = t(`cplug.huddle.tm.month_${p.month}`);
  return p.year === now.year ? t('cplug.huddle.tm.month_day', { month, day: p.day }) : t('cplug.huddle.tm.month_day_year', { month, day: p.day, year: String(p.year) });
}

export function messageClock(atSec: number, nowSec: number, zone: string): string {
  const at = partsIn(atSec, zone);
  const now = partsIn(nowSec, zone);
  return sameDay(at, now) ? clockOf(at) : dateOf(at, now);
}

export function ageWords(atSec: number, nowSec: number, zone: string): string {
  const s = Math.max(0, Math.round(nowSec - atSec));
  if (s < MINUTE_S) return t('cplug.huddle.tm.age_now');
  if (s < HOUR_S) return t('cplug.huddle.tm.age_m', { n: Math.floor(s / MINUTE_S) });
  if (s < AGE_HOURS_SHOWN * HOUR_S) return t('cplug.huddle.tm.age_h', { n: Math.floor(s / HOUR_S) });
  const at = partsIn(atSec, zone);
  const now = partsIn(nowSec, zone);
  return sameDay(at, now) ? t('cplug.huddle.tm.age_today') : dateOf(at, now);
}

export function closedWords(atSec: number, nowSec: number, zone: string): string {
  const s = Math.max(0, Math.round(nowSec - atSec));
  if (s < MINUTE_S) return t('cplug.huddle.tm.closed_ago', { age: t('cplug.huddle.tm.age_m', { n: 1 }) });
  if (s < HOUR_S) return t('cplug.huddle.tm.closed_ago', { age: t('cplug.huddle.tm.age_m', { n: Math.floor(s / MINUTE_S) }) });
  const at = partsIn(atSec, zone);
  const now = partsIn(nowSec, zone);
  return sameDay(at, now) ? t('cplug.huddle.tm.closed_earlier_today') : dateOf(at, now);
}

export function runWords(atSec: number, nowSec: number, zone: string): string {
  const at = partsIn(atSec, zone);
  const now = partsIn(nowSec, zone);
  return t('cplug.huddle.tm.run_at', { day: sameDay(at, now) ? t('cplug.huddle.tm.age_today') : dateOf(at, now), time: clockOf(at) });
}

export function closerText(task: Pick<Task, 'closedBy'>): string {
  if (!task.closedBy) return t('cplug.huddle.tm.not_recorded');
  return task.closedBy === OWNER ? t('cplug.huddle.tm.you') : task.closedBy;
}
