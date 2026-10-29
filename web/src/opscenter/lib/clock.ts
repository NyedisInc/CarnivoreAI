/* scheduled tasks */
import { t } from '../../lib/i18n/index.svelte';

const DAY_MS = 86_400_000;

let timeFormat: Intl.DateTimeFormat | null = null;
let dateFormat: Intl.DateTimeFormat | null = null;

function timeFormatter(): Intl.DateTimeFormat {
  timeFormat ??= new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });
  return timeFormat;
}

function dateFormatter(): Intl.DateTimeFormat {
  dateFormat ??= new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });
  return dateFormat;
}

export function clockText(ms: number): string {
  return timeFormatter().format(new Date(ms)).toLowerCase();
}

function dayStart(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function dayClockText(ms: number, nowMs: number): string {
  const time = clockText(ms);
  const days = Math.round((dayStart(ms) - dayStart(nowMs)) / DAY_MS);
  if (days === 0) return t('opscenter.time.day_today', { time });
  if (days === 1) return t('opscenter.time.day_tomorrow', { time });
  if (days === -1) return t('opscenter.time.day_yesterday', { time });
  const date = dateFormatter().format(new Date(ms)).toLowerCase();
  return t('opscenter.time.day_date', { date, time });
}
