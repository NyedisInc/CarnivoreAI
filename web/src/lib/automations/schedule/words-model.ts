import { t } from '../../i18n/index.svelte';
import type { ParsedFire, ScheduleParse } from '../api';
import { cronFields, dayList } from './compose';
import type { Clock } from '../logic/words';

export function fireText(clock: Clock, epoch: number, list: readonly number[]): string {
  const line = clock.when(epoch);
  return Math.max(...list) - Math.min(...list) > 300 * 86400 ? line.replace(/^(\w+ \d+),/, `$1 ${new Date(epoch * 1000).getFullYear()},`) : line;
}

const NUM = /^\d+$/;
const STEP = /^\*\/(\d+)$/;

export function clockText(hour: number, minute: number): string {
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')} ${hour < 12 ? 'am' : 'pm'}`;
}

export function nthWord(n: number): string {
  return t(`automations.simple.ordinal.${n}`);
}

export function dayName(day: number): string {
  return t(`automations.simple.day.${day % 7}`);
}

export function monthName(month: number): string {
  return t(`automations.simple.month.${month}`);
}

export function dayOrdinal(n: number): string {
  const rule = new Intl.PluralRules('en', { type: 'ordinal' }).select(n);
  return `${n}${t(`automations.simple.ordinal_suffix.${rule}`)}`;
}

function dayPhrase(ds: number[]): string {
  const key = ds.join(',');
  if (ds.length === 7) return t('automations.simple.cadence.every_day');
  if (key === '1,2,3,4,5') return t('automations.simple.cadence.weekdays');
  if (key === '0,6') return t('automations.simple.cadence.weekends');
  if (ds.length === 1) return t('automations.simple.cadence.every_one_day', { day: dayName(ds[0] as number) });
  const names = ds.map((d) => t('automations.simple.cadence.plural_day', { day: dayName(d) }));
  return t('automations.simple.cadence.day_list', { days: names.slice(0, -1).join(', '), last: names[names.length - 1] as string });
}

function hoursPhrase(step: number | null, minute: number): string {
  const base = step === null || step === 1 ? t('automations.simple.cadence.every_hour') : t('automations.simple.cadence.every_n_hours', { n: step });
  return minute ? t('automations.simple.cadence.at_minutes', { base, min: minute }) : t('automations.simple.cadence.on_the_hour', { base });
}

export function cronToWords(cron: string): string | null {
  const f = cronFields(cron);
  if (f.length !== 5) return null;
  const [mi, h, dom, mon, dow] = f as [string, string, string, string, string];
  const minStep = STEP.exec(mi);
  if (minStep && h === '*' && dom === '*' && mon === '*' && dow === '*') {
    return Number(minStep[1]) === 1 ? t('automations.simple.cadence.every_minute') : `${t('automations.simple.pick.every')} ${t('automations.simple.pick.minutes_many', { n: Number(minStep[1]) })}`;
  }
  if (!NUM.test(mi) || Number(mi) > 59) return null;
  const hourStep = STEP.exec(h);
  if ((h === '*' || hourStep) && dom === '*' && mon === '*' && dow === '*') return hoursPhrase(hourStep ? Number(hourStep[1]) : null, Number(mi));
  if (!NUM.test(h) || Number(h) > 23) return null;
  const time = clockText(Number(h), Number(mi));
  if (mon === '*' && dom === '*') {
    if (dow === '*') return t('automations.simple.cadence.days_at', { days: t('automations.simple.cadence.every_day'), time });
    const nth = /^(\d)#([1-5])$/.exec(dow);
    if (nth) return t('automations.simple.cadence.nth_weekday', { nth: nthWord(Number(nth[2])), day: dayName(Number(nth[1])), time });
    const ds = dayList(dow);
    return ds ? t('automations.simple.cadence.days_at', { days: dayPhrase(ds), time }) : null;
  }
  const dayOk = NUM.test(dom) && Number(dom) >= 1 && Number(dom) <= 31;
  if (mon === '*' && dow === '*' && dayOk) {
    const days = `${t('automations.simple.pick.the_ordinal', { ordinal: dayOrdinal(Number(dom)) })} ${t('automations.simple.pick.of_every_month')}`;
    return t('automations.simple.cadence.days_at', { days, time });
  }
  if (dow === '*' && dayOk && NUM.test(mon) && Number(mon) >= 1 && Number(mon) <= 12) {
    return t('automations.simple.cadence.yearly', { month: monthName(Number(mon)), day: Number(dom), time });
  }
  return null;
}

export function browserZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export function zonesDiffer(fires: readonly ParsedFire[]): boolean {
  return fires.some((x) => x.in_zone !== x.local);
}

export interface FireLine {
  inZone: string;
  local: string;
}

export type WordsOutcome =
  | {
      kind: 'ok';
      cron: string;
      words: string;
      fires: FireLine[];
      differs: boolean;
    }
  | { kind: 'refused'; reason: string; text: string };

export function parseOutcome(parse: ScheduleParse): WordsOutcome {
  if (!parse.ok) {
    const key = `automations.simple.reason.${parse.reason}`;
    const known = t(key);
    return { kind: 'refused', reason: parse.reason, text: known === key ? (parse.message ?? parse.reason) : known };
  }
  return {
    kind: 'ok',
    cron: parse.cron,
    words: cronToWords(parse.cron) ?? parse.explain ?? '',
    fires: parse.fires.map((x) => ({ inZone: x.in_zone, local: x.local })),
    differs: zonesDiffer(parse.fires),
  };
}

export function createBlockedReason(pending: WordsOutcome | null): string | null {
  return pending && pending.kind === 'ok' ? t('automations.simple.reason.pending') : null;
}
