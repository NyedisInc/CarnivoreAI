import { t } from '../../i18n/index.svelte';

export type Repeat = 'daily' | 'days' | 'nth' | 'monthdate' | 'yeardate' | 'hours' | 'minutes';

export const REPEATS: readonly Repeat[] = ['daily', 'days', 'nth', 'monthdate', 'yeardate', 'hours', 'minutes'];

export const MINUTE_STEPS: readonly number[] = [15, 20, 30];
export const HOUR_STEPS: readonly number[] = [1, 2, 3, 4, 6, 8, 12];

export interface PickState {
  rep: Repeat;
  step: number;
  min: number;
  hour12: number;
  ap: 'am' | 'pm';
  days: number[];
  nth: number;
  wd: number;
  dom: number;
  month: number;
}

const NUM = /^\d+$/;
const STEP = /^\*\/(\d+)$/;
const DAY_NAMES = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const MONTH_NAMES = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];

export function defaultPick(): PickState {
  return { rep: 'days', step: 2, min: 0, hour12: 9, ap: 'am', days: [1, 2, 3, 4, 5], nth: 1, wd: 1, dom: 1, month: 1 };
}

export function cronFields(cron: string): string[] {
  return String(cron ?? '')
    .trim()
    .toLowerCase()
    .replace(/\b(sun|mon|tue|wed|thu|fri|sat)\b/g, (d) => String(DAY_NAMES.indexOf(d)))
    .replace(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b/g, (m) => String(MONTH_NAMES.indexOf(m) + 1))
    .split(/\s+/)
    .filter((f) => f !== '');
}

export function dayList(dow: string): number[] | null {
  const out = new Set<number>();
  for (const part of dow.split(',')) {
    const m = /^(\d)(?:-(\d))?$/.exec(part);
    if (!m) return null;
    const a = Number(m[1]);
    const b = m[2] !== undefined ? Number(m[2]) : a;
    if (a > 7 || b > 7 || b < a) return null;
    for (let i = a; i <= b; i++) out.add(i % 7);
  }
  return [...out].sort((x, y) => x - y);
}

export function parsePick(cron: string): PickState | null {
  const f = cronFields(cron);
  if (f.length !== 5) return null;
  const [mi, h, dom, mon, dow] = f as [string, string, string, string, string];
  const base = defaultPick();
  const minStep = STEP.exec(mi);
  if (minStep && h === '*' && dom === '*' && mon === '*' && dow === '*') return { ...base, rep: 'minutes', step: Number(minStep[1]) };
  const hourStep = STEP.exec(h);
  if (NUM.test(mi) && Number(mi) <= 59 && (h === '*' || hourStep) && dom === '*' && mon === '*' && dow === '*') {
    return { ...base, rep: 'hours', step: hourStep ? Number(hourStep[1]) : 1, min: Number(mi) };
  }
  if (!NUM.test(mi) || !NUM.test(h) || Number(mi) > 59 || Number(h) > 23) return null;
  const clock = { min: Number(mi), hour12: Number(h) % 12 || 12, ap: Number(h) < 12 ? ('am' as const) : ('pm' as const) };
  if (mon === '*' && dom === '*') {
    if (dow === '*') return { ...base, ...clock, rep: 'daily' };
    const nth = /^(\d)#([1-4])$/.exec(dow);
    if (nth) return { ...base, ...clock, rep: 'nth', wd: Number(nth[1]) % 7, nth: Number(nth[2]) };
    const days = dayList(dow);
    return days ? { ...base, ...clock, rep: 'days', days } : null;
  }
  const dayOk = NUM.test(dom) && Number(dom) >= 1 && Number(dom) <= 31;
  if (mon === '*' && dow === '*' && dayOk) return { ...base, ...clock, rep: 'monthdate', dom: Number(dom) };
  if (dow === '*' && dayOk && NUM.test(mon) && Number(mon) >= 1 && Number(mon) <= 12) {
    return { ...base, ...clock, rep: 'yeardate', dom: Number(dom), month: Number(mon) };
  }
  return null;
}

export function buildCron(s: PickState): string {
  if (s.rep === 'minutes') return `*/${s.step} * * * *`;
  if (s.rep === 'hours') return `${s.min}${s.step === 1 ? ' * * * *' : ` */${s.step} * * *`}`;
  const hour = (s.hour12 % 12) + (s.ap === 'pm' ? 12 : 0);
  const time = `${s.min} ${hour}`;
  if (s.rep === 'daily') return `${time} * * *`;
  if (s.rep === 'nth') return `${time} * * ${s.wd}#${s.nth}`;
  if (s.rep === 'monthdate') return `${time} ${s.dom} * *`;
  if (s.rep === 'yeardate') return `${time} ${s.dom} ${s.month} *`;
  const ds = [...s.days].sort((a, b) => a - b);
  const run = ds.length > 2 && ds.every((d, i) => i === 0 || d === (ds[i - 1] as number) + 1);
  const first = ds[0] as number;
  const last = ds[ds.length - 1] as number;
  return `${time} * * ${ds.length === 0 ? '1' : run ? `${first}-${last}` : ds.join(',')}`;
}

export function changeRepeat(s: PickState, rep: Repeat, today: { month: number; day: number } = { month: 1, day: 1 }): PickState {
  const next: PickState = { ...s, rep };
  const dated = (r: Repeat): boolean => r === 'monthdate' || r === 'yeardate';
  if (dated(rep) && !dated(s.rep)) {
    next.dom = today.day;
    next.month = today.month;
  }
  if (rep === 'nth' && s.rep !== 'nth') {
    next.nth = 3;
    next.wd = 2;
  }
  if (rep === 'minutes' && !MINUTE_STEPS.includes(s.step)) next.step = 30;
  if (rep === 'hours' && !HOUR_STEPS.includes(s.step)) next.step = 2;
  return next;
}

export type CronCheck =
  | { ok: true }
  | { ok: false; code: 'fields' | 'field_bad' | 'never' | 'too_often'; text: string };

const LIMITS: ReadonlyArray<readonly [number, number]> = [[0, 59], [0, 23], [1, 31], [1, 12], [0, 7]];
const FIELD_KEYS = ['minute', 'hour', 'dom', 'month', 'dow'] as const;
const ITEM = /^(\*|(\d+)(?:-(\d+))?(?:#([1-5]))?)(?:\/(\d+))?$/;

function itemValues(item: string, i: number): number[] | null {
  const m = ITEM.exec(item);
  const lim = LIMITS[i];
  if (!m || !lim) return null;
  if (m[4] !== undefined && i !== 4) return null;
  if (m[4] !== undefined && m[5] !== undefined) return null;
  const step = m[5] !== undefined ? Number(m[5]) : 1;
  if (step < 1) return null;
  const a = m[2] !== undefined ? Number(m[2]) : lim[0];
  const b = m[3] !== undefined ? Number(m[3]) : m[1] === '*' || m[5] !== undefined ? lim[1] : a;
  if (a < lim[0] || b > lim[1] || a > b) return null;
  const out: number[] = [];
  for (let v = a; v <= b; v += step) out.push(v);
  return out;
}

function fieldValues(field: string, i: number): Set<number> | null {
  const out = new Set<number>();
  for (const item of field.split(',')) {
    const vals = itemValues(item, i);
    if (!vals) return null;
    vals.forEach((v) => out.add(v));
  }
  return out;
}

function shortestGap(minutes: number[], hours: number[], wraps: boolean): number {
  const times = hours.flatMap((h) => minutes.map((m) => h * 60 + m)).sort((a, b) => a - b);
  let gap = Infinity;
  for (let j = 1; j < times.length; j++) gap = Math.min(gap, (times[j] as number) - (times[j - 1] as number));
  if (wraps && times.length > 0) gap = Math.min(gap, (times[0] as number) + 1440 - (times[times.length - 1] as number));
  return gap;
}

function neverFiresByCalendar(dom: Set<number>, mon: Set<number>, dowFree: boolean): boolean {
  if (!dowFree) return false;
  const longest: Record<number, number> = { 1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31 };
  return ![...mon].some((m) => [...dom].some((d) => d <= (longest[m] as number)));
}

export function checkCron(cron: string): CronCheck {
  const raw = String(cron ?? '').trim().split(/\s+/).filter((x) => x !== '');
  if (raw.length !== 5) return { ok: false, code: 'fields', text: t('automations.simple.check.fields') };
  const f = cronFields(cron);
  const sets: Set<number>[] = [];
  for (let i = 0; i < 5; i++) {
    const vals = f[i] === undefined ? null : fieldValues(f[i] as string, i);
    if (!vals) {
      return { ok: false, code: 'field_bad', text: t('automations.simple.check.field_bad', { field: t(`automations.simple.check.field.${FIELD_KEYS[i]}`) }) };
    }
    sets.push(vals);
  }
  const [minutes, hours, dom, mon] = sets as [Set<number>, Set<number>, Set<number>, Set<number>, Set<number>];
  if (neverFiresByCalendar(dom, mon, f[4] === '*')) {
    return { ok: false, code: 'never', text: t('automations.simple.check.never') };
  }
  const wraps = f[2] === '*' && f[3] === '*' && f[4] === '*';
  if (shortestGap([...minutes], [...hours], wraps) < 15) return { ok: false, code: 'too_often', text: t('automations.simple.check.too_often') };
  return { ok: true };
}
