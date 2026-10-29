import { t } from '../../i18n/index.svelte';
import type { DiffResult } from './diff';
import type { AutomationSignals } from './signals';
import type { CounterId } from './types';
import { bytesWords, type Clock, countWords, runTime, secsWords, skipSentence, statusWord } from './words';

export interface ListRow {
  id: string;
  name: string;
  enabled: boolean;
  kindLabel: string;
  cronWords: string;
  nextFireAt: number | null;
  sig: AutomationSignals;
}

export const SORT_KEYS = ['light', 'name', 'sched', 'next', 'last', 'rate', 'med', 'on'] as const;
export type SortKey = (typeof SORT_KEYS)[number];

export const DESC_FIRST: ReadonlySet<SortKey> = new Set<SortKey>(['last', 'rate', 'med']);

function keyOf(v: ListRow, k: SortKey): number | string {
  const l = v.sig.last;
  switch (k) {
    case 'light':
      return v.sig.attentionRank;
    case 'name':
      return v.name.toLowerCase();
    case 'sched':
      return v.cronWords;
    case 'next':
      return v.nextFireAt == null || !v.enabled ? Infinity : v.nextFireAt;
    case 'last':
      return l ? runTime(l) : -Infinity;
    case 'rate':
      return v.sig.rate.v;
    case 'med':
      return v.sig.median == null ? -1 : v.sig.median;
    case 'on':
      return v.enabled ? 0 : 1;
  }
}

export function sortRows(rows: ListRow[], k: SortKey, d: 1 | -1): ListRow[] {
  return [...rows].sort((a, b) => {
    const x = keyOf(a, k);
    const y = keyOf(b, k);
    return (x < y ? -1 : x > y ? 1 : a.name.localeCompare(b.name)) * d;
  });
}

export type Pill = { k: 'status'; v: string } | { k: 'kind'; v: string };

export const PILL_STATUSES = ['failed', 'succeeded', 'skipped', 'running', 'waiting_on_you', 'no run'] as const;

export function pillTest(v: ListRow, f: Pill): boolean {
  const l = v.sig.last;
  if (f.k === 'status') return f.v === 'no run' ? !l : !!l && l.status === f.v;
  return v.kindLabel === f.v;
}

export function pillWords(f: Pill): string {
  return f.k === 'status'
    ? t('automations.page.pill.status', { v: f.v === 'no run' ? t('automations.page.pill.no_run') : statusWord(f.v) })
    : t('automations.page.pill.kind', { v: f.v });
}

export interface ListFilters {
  q: string;
  pills: Pill[];
  pressed: CounterId[];
  counterIds: Partial<Record<CounterId, string[]>>;
  where: ((id: string) => boolean) | null;
}

export function filterRows(rows: ListRow[], f: ListFilters, haystack: (v: ListRow) => string): ListRow[] {
  const q = f.q.trim().toLowerCase();
  const union = f.pressed.length ? new Set(f.pressed.flatMap((id) => f.counterIds[id] ?? [])) : null;
  return rows.filter((v) => (!union || union.has(v.id)) && (!f.where || f.where(v.id)) && f.pills.every((p) => pillTest(v, p)) && (!q || haystack(v).includes(q)));
}

export interface HeaderFacts {
  total: number;
  on: number;
  attention: number;
  paused: boolean;
  next: { name: string; at: number } | null;
  runs24h: number;
  failed24h: number;
}

export function headerSentence(f: HeaderFacts, clock: Clock, now: number): string {
  if (!f.total) return '';
  const bits = [
    countWords('automations.page.count.automation', f.total),
    t('automations.page.sentence.on', { n: f.on }),
    t(f.attention === 1 ? 'automations.page.sentence.needs_one' : 'automations.page.sentence.needs_many', { n: f.attention }),
  ];
  if (f.paused) bits.push(t('automations.page.sentence.paused'));
  else if (f.next) bits.push(t('automations.page.sentence.next', { name: f.next.name, when: clock.short(f.next.at, now) }));
  bits.push(
    t('automations.page.sentence.last24', { runs: countWords('automations.page.count.run', f.runs24h) }) +
      (f.failed24h ? t('automations.page.sentence.failed', { n: f.failed24h }) : ''),
  );
  return bits.join(' · ');
}

export interface PreviewRun {
  number: number;
  status: string;
  reason: string | null;
  skip_count: number | null;
  first_slot_at?: number | null;
  last_slot_at?: number | null;
  started_at: number | null;
  ended_at: number | null;
  slot_at: number | null;
  created_at?: number | null;
  report_bytes: number | null;
}

export function previewText(run: PreviewRun, cmp: DiffResult | null, clock: Clock, tz: string): string {
  const bits = [`#${run.number}`, clock.when(runTime(run))];
  if (run.status !== 'succeeded') bits.push(statusWord(run.status));
  if (run.started_at != null && run.ended_at != null) bits.push(t('automations.page.empty.took', { took: secsWords(run.ended_at - run.started_at) }));
  if (run.report_bytes) bits.push(bytesWords(run.report_bytes));
  if (cmp) bits.push(cmp.sentence + (cmp.base && !cmp.same ? t('automations.page.diff.vs', { n: cmp.base.number }) : ''));
  else if (run.status === 'skipped') bits.push(skipSentence(run, tz));
  return bits.join(' · ');
}
