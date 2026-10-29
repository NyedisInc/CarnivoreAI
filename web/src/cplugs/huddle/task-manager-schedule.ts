import type { HuddleItem, TaskManagerRepeat } from './huddle-model';

export type DueState = 'pending' | 'fired' | 'failed' | 'paused';

export interface DueWords {
  today: string;
  tomorrow: string;
}

const DAY_MS = 86_400_000;
const WEEKDAY_SPAN = 6;

export function dueState(item: Pick<HuddleItem, 'start_trigger'>): DueState | null {
  const trigger = item.start_trigger;
  if (!trigger) return null;
  if (trigger.repeat) return trigger.paused ? 'paused' : trigger.last_error ? 'failed' : 'pending';
  if (trigger.last_error) return 'failed';
  return trigger.fired_at !== null ? 'fired' : 'pending';
}

function dayStart(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

export function dueLabel(epochSeconds: number, now: Date, words: DueWords, locale?: string): string {
  const at = new Date(epochSeconds * 1000);
  const time = at.toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  const days = Math.round((dayStart(at) - dayStart(now)) / DAY_MS);
  if (days === 0) return `${words.today} ${time}`;
  if (days === 1) return `${words.tomorrow} ${time}`;
  if (days > 1 && days <= WEEKDAY_SPAN) return `${at.toLocaleDateString(locale, { weekday: 'short' }).toLowerCase()} ${time}`;
  return `${at.toLocaleDateString(locale, { month: 'short', day: 'numeric' }).toLowerCase()} ${time}`;
}

const two = (n: number): string => String(n).padStart(2, '0');

export function toLocalInput(epochSeconds: number): string {
  const d = new Date(epochSeconds * 1000);
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`;
}

export function defaultLocalInput(now: Date): string {
  const next = new Date(now.getFullYear(), now.getMonth(), now.getDate(), now.getHours() + 1, 0, 0);
  return toLocalInput(next.getTime() / 1000);
}

export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const moment = new Date(value);
  return Number.isNaN(moment.getTime()) ? null : moment.toISOString();
}

export type RepeatKind = 'none' | 'daily' | 'weekly' | 'hours' | 'monthly';
export const REPEAT_KINDS: readonly RepeatKind[] = ['none', 'daily', 'weekly', 'hours', 'monthly'];
export const WORKDAYS: readonly number[] = [0, 1, 2, 3, 4];
export const MAX_HOURS = 168;

export interface RepeatDraft {
  kind: RepeatKind;
  hours: number;
  days: number[];
  monthday: number;
}

export const defaultRepeat = (): RepeatDraft => ({ kind: 'none', hours: 4, days: [...WORKDAYS], monthday: 1 });

export function draftOf(rule: TaskManagerRepeat | null | undefined): RepeatDraft {
  const base = defaultRepeat();
  if (!rule) return base;
  if (rule.freq === 'hourly') return { ...base, kind: 'hours', hours: rule.interval ?? 1 };
  if (rule.freq === 'weekly') return { ...base, kind: 'weekly', days: [...(rule.byweekday ?? WORKDAYS)] };
  return rule.freq === 'monthly' ? { ...base, kind: 'monthly', monthday: rule.monthday ?? 1 } : { ...base, kind: 'daily' };
}

export function ruleFromDraft(draft: RepeatDraft, value: string): TaskManagerRepeat | null {
  if (draft.kind === 'none') return null;
  if (draft.kind === 'hours') return { freq: 'hourly', interval: Math.min(Math.max(Math.trunc(draft.hours) || 1, 1), MAX_HOURS) };
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2})/.exec(value);
  if (!match) return null;
  if (draft.kind === 'daily') return { freq: 'daily', time: match[4] };
  if (draft.kind === 'weekly') return draft.days.length ? { freq: 'weekly', byweekday: [...draft.days].sort(), time: match[4] } : null;
  return { freq: 'monthly', monthday: Math.min(Math.max(Math.trunc(draft.monthday) || 1, 1), 31), time: match[4] };
}

export function clockLabel(time: string, locale?: string): string {
  const [hour, minute] = time.split(':').map(Number);
  return new Date(2026, 0, 1, hour, minute).toLocaleTimeString(locale, { hour: 'numeric', minute: '2-digit' }).toLowerCase();
}

const dayName = (day: number, locale?: string): string => new Date(2026, 9, 5 + day).toLocaleDateString(locale, { weekday: 'short' }).toLowerCase();

export function repeatLabel(rule: TaskManagerRepeat, tr: (key: string, params?: Record<string, string | number>) => string, locale?: string): string {
  const time = rule.time ? clockLabel(rule.time, locale) : '';
  if (rule.freq === 'hourly') return rule.interval && rule.interval > 1 ? tr('cplug.huddle.schedule.repeat_hours', { n: rule.interval }) : tr('cplug.huddle.schedule.repeat_hour');
  if (rule.freq === 'monthly') return tr('cplug.huddle.schedule.repeat_monthly', { day: rule.monthday ?? 1, time });
  if (rule.freq === 'weekly') {
    const days = rule.byweekday ?? [];
    if (days.join() === WORKDAYS.join()) return tr('cplug.huddle.schedule.repeat_weekdays', { time });
    return `${days.map((d) => dayName(d, locale)).join(', ')} ${time}`;
  }
  return tr('cplug.huddle.schedule.repeat_daily', { time });
}

export interface EditorDraft {
  title: string;
  text: string;
  when: string;
  plan: RepeatDraft;
}

export function editorDraft(item: Pick<HuddleItem, 'title' | 'text' | 'start_trigger'> | null, now: Date): EditorDraft {
  const trigger = item?.start_trigger ?? null;
  const when = trigger ? toLocalInput(trigger.fire_at) : defaultLocalInput(now);
  const plan = draftOf(trigger?.repeat);
  if (!trigger?.repeat) plan.monthday = Number(when.slice(8, 10)) || 1;
  return { title: item?.title ?? '', text: item?.text ?? '', when, plan };
}

export function scheduleFields(draft: EditorDraft, repeating: boolean): { fire_at?: string; repeat?: TaskManagerRepeat | '' } | null {
  const iso = fromLocalInput(draft.when);
  if (!iso) return null;
  const rule = ruleFromDraft(draft.plan, draft.when);
  if (draft.plan.kind !== 'none' && !rule) return null;
  return rule && rule.freq !== 'hourly' ? { repeat: rule } : { fire_at: iso, repeat: rule ?? (repeating ? '' : undefined) };
}

export function editBody(item: HuddleItem, draft: EditorDraft, withSchedule: boolean): Record<string, unknown> | null {
  const body: Record<string, unknown> = {};
  if (draft.text.trim() !== item.text.trim()) body.text = draft.text;
  if (draft.title.trim() !== (item.title ?? '').trim()) body.title = draft.title;
  const trigger = item.start_trigger ?? null;
  const before = editorDraft(item, new Date());
  const moved = !trigger || draft.when !== before.when || JSON.stringify(draft.plan) !== JSON.stringify(before.plan);
  if (withSchedule && moved) {
    const fields = scheduleFields(draft, Boolean(trigger?.repeat));
    if (!fields) return null;
    Object.assign(body, fields);
  }
  return body;
}

export function addBody(draft: EditorDraft, armed: boolean): Record<string, unknown> | null {
  if (!draft.text.trim()) return null;
  const body: Record<string, unknown> = { text: draft.text };
  if (draft.title.trim()) body.title = draft.title;
  if (!armed) return body;
  const iso = fromLocalInput(draft.when);
  const rule = ruleFromDraft(draft.plan, draft.when);
  if (!iso || (draft.plan.kind !== 'none' && !rule)) return null;
  body.fire_at = iso;
  if (rule) body.repeat = rule;
  return body;
}
