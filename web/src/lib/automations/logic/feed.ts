import { t } from '../../i18n/index.svelte';
import { compare, normalizeSlot, stable, usableReport, type DiffRun } from './diff';
import { face, type RuleContext } from './report-rules';
import type { ReportLookup, ReportSlot } from './types';
import { type Clock, bucketByDay, isLive, runStatusWord, runTime, statusWord, triggerWord } from './words';

export interface FeedRow extends DiffRun {
  automation_id: string;
  automation_name?: string;
  trigger: string;
  attempt?: number | null;
  slot_at: number | null;
  created_at?: number | null;
  reason: string | null;
  error: string | null;
  skip_count: number | null;
  first_slot_at?: number | null;
  last_slot_at?: number | null;
  has_report: boolean;
  host?: string | null;
}

export interface RunInfo {
  pred: FeedRow | null;
  first: boolean;
  same: boolean;
  pending: boolean;
}

export function slotOf(run: Pick<FeedRow, 'run_id' | 'has_report' | 'status'>, lookup: ReportLookup): ReportSlot {
  if (!run.has_report) return { state: 'ready', report: null };
  return normalizeSlot(lookup(run.run_id));
}

const SAME_MEMO_MAX = 2000;
const sameMemo = new Map<string, { a: unknown; b: unknown; same: boolean }>();

function sameByDiff(p: FeedRow, pSlot: ReportSlot, r: FeedRow, rSlot: ReportSlot, retryStatusWord: (s: string) => string): boolean {
  const key = `${p.run_id}|${r.run_id}`;
  const a = rSlot.state === 'ready' ? rSlot.report : undefined;
  const b = pSlot.state === 'ready' ? pSlot.report : undefined;
  const hit = sameMemo.get(key);
  if (hit && hit.a === a && hit.b === b) return hit.same;
  const same = compare({ run: p, slot: pSlot }, { run: r, slot: rSlot }, { statusWord: retryStatusWord }).same;
  if (sameMemo.size >= SAME_MEMO_MAX) sameMemo.clear();
  sameMemo.set(key, { a, b, same });
  return same;
}

function sameAs(r: FeedRow, p: FeedRow, lookup: ReportLookup, retryStatusWord: (s: string) => string): { same: boolean; pending: boolean } {
  if (isLive(r.status) || isLive(p.status)) return { same: false, pending: false };
  if (r.status !== p.status || (r.reason ?? '') !== (p.reason ?? '')) return { same: false, pending: false };
  if (r.status === 'skipped') return { same: true, pending: false };
  const a = slotOf(r, lookup);
  const b = slotOf(p, lookup);
  if (a.state === 'pending' || b.state === 'pending') return { same: false, pending: true };
  if (a.state === 'unreadable' || b.state === 'unreadable') return { same: false, pending: false };
  if (r.status === 'failed') return { same: (r.error ?? '') === (p.error ?? '') && stable(a.report ?? null) === stable(b.report ?? null), pending: false };
  if (stable(a.report ?? null) === stable(b.report ?? null)) return { same: true, pending: false };
  return { same: sameByDiff(p, b, r, a, retryStatusWord), pending: false };
}

export function analyse(runs: FeedRow[], older: FeedRow[], lookup: ReportLookup): Map<string, RunInfo> {
  const by = new Map<string, FeedRow[]>();
  for (const r of [...runs, ...older]) {
    const list = by.get(r.automation_id);
    if (list) list.push(r);
    else by.set(r.automation_id, [r]);
  }
  const info = new Map<string, RunInfo>();
  for (const list of by.values()) {
    list.forEach((r, i) => {
      const p = list[i + 1] ?? null;
      if (!p) {
        const slot = r.status === 'succeeded' || r.status === 'failed' ? slotOf(r, lookup) : null;
        info.set(r.run_id, { pred: null, first: true, same: false, pending: slot?.state === 'pending' });
        return;
      }
      const own = r.status === 'succeeded' || r.status === 'failed' ? slotOf(r, lookup) : null;
      if (own?.state === 'pending') {
        info.set(r.run_id, { pred: p, first: false, same: false, pending: true });
        return;
      }
      const res = sameAs(r, p, lookup, statusWord);
      info.set(r.run_id, { pred: p, first: false, same: res.same, pending: res.pending });
    });
  }
  return info;
}

export function infoOf(info: Map<string, RunInfo>, run: { run_id: string }): RunInfo {
  return info.get(run.run_id) ?? { pred: null, first: true, same: false, pending: false };
}

export function changed(info: Map<string, RunInfo>, run: { run_id: string }): boolean {
  const i = infoOf(info, run);
  return !i.pending && !i.same;
}


export interface UnreadState {
  seenAt: string | null;
  read: ReadonlySet<string>;
}

export function seenAtEpoch(seenAt: string | null, now: number): number {
  if (seenAt) {
    const ms = Date.parse(seenAt);
    if (Number.isFinite(ms)) return ms / 1000;
  }
  return now - 86400;
}

export function isUnread(run: { run_id: string } & Parameters<typeof runTime>[0], state: UnreadState, now: number): boolean {
  return runTime(run) > seenAtEpoch(state.seenAt, now) && !state.read.has(run.run_id);
}

export function appendRead(read: readonly string[], ids: readonly string[], cap = 500): string[] {
  const out = read.filter((id) => !ids.includes(id));
  out.push(...ids);
  return out.slice(Math.max(0, out.length - cap));
}

export function mergeRead(
  server: { seenAt: string | null; read: readonly string[] },
  local: { seenAt: string | null; read: readonly string[] },
): { seenAt: string | null; read: string[] } {
  const seen = new Set<string>();
  const read: string[] = [];
  for (const id of [...server.read, ...local.read]) if (!seen.has(id)) (seen.add(id), read.push(id));
  const later = (server.seenAt ?? '') >= (local.seenAt ?? '') ? server.seenAt : local.seenAt;
  return { seenAt: later, read: read.slice(Math.max(0, read.length - 500)) };
}


export interface FeedFilters {
  q: string;
  changedOnly: boolean;
  unreadOnly: boolean;
}

const textMemo = new WeakMap<object, string>();
const SEARCH_TEXT_MAX = 30000;

function reportText(rep: unknown): string {
  if (rep === undefined) return '';
  if (typeof rep !== 'object' || rep === null) return (JSON.stringify(rep) ?? '').slice(0, SEARCH_TEXT_MAX);
  const hit = textMemo.get(rep);
  if (hit !== undefined) return hit;
  const text = (JSON.stringify(rep) ?? '').slice(0, SEARCH_TEXT_MAX);
  textMemo.set(rep, text);
  return text;
}

export function haystack(run: FeedRow, slot: ReportSlot, ctx: RuleContext, retryMax: number): string {
  const text = reportText(usableReport(slot));
  return [run.automation_name ?? '', face(run, slot, ctx).text, runStatusWord(run), triggerWord(run, retryMax), run.error ?? '', text].join(' ').toLowerCase();
}

export function filtersActive(f: FeedFilters): boolean {
  return !!(f.q.trim() || f.changedOnly || f.unreadOnly);
}


export interface FeedEntry {
  type: 'run' | 'fold';
  key: string;
  run: FeedRow;
  members: FeedRow[];
  time: number;
  repeat?: boolean;
  from?: number;
  to?: number;
}

export function entries(runs: FeedRow[], info: Map<string, RunInfo>, changedOnly: boolean, clock: Clock): FeedEntry[] {
  const res: FeedEntry[] = [];
  const open = new Map<string, FeedEntry & { day: string }>();
  for (const r of runs) {
    const inf = infoOf(info, r);
    const foldable = inf.same && !inf.pending && !changedOnly && (r.status === 'succeeded' || r.status === 'skipped');
    if (!foldable) {
      open.delete(r.automation_id);
      res.push({ type: 'run', key: `r:${r.run_id}`, run: r, members: [r], time: runTime(r) });
      continue;
    }
    const dk = clock.dayKey(runTime(r));
    const g = open.get(r.automation_id);
    if (g && g.day === dk) {
      g.members.push(r);
      continue;
    }
    const fold = { type: 'fold' as const, day: dk, key: '', run: r, members: [r], time: runTime(r) };
    open.set(r.automation_id, fold);
    res.push(fold);
  }
  for (const g of res) {
    if (g.type !== 'fold') continue;
    if (g.members.length === 1) {
      g.type = 'run';
      g.key = `r:${g.run.run_id}`;
      g.repeat = true;
      continue;
    }
    const old = g.members[g.members.length - 1]!;
    g.key = `f:${old.run_id}`;
    g.from = runTime(old);
    g.to = runTime(g.run);
  }
  return res;
}

export function foldText(g: FeedEntry, faceText: string, clock: Clock): string {
  const key = g.run.status === 'skipped' ? 'automations.page.fold.same_reason' : 'automations.page.fold.same_output';
  return t(key, { n: g.members.length, face: faceText, from: clock.hm24(g.from ?? g.time), to: clock.hm24(g.to ?? g.time) });
}

export interface FeedDay {
  key: string;
  label: string;
  entries: FeedEntry[];
  runs: number;
}

export interface FeedPage {
  days: FeedDay[];
  shown: FeedEntry[];
  rest: FeedEntry[];
  runsShown: number;
}

export function page(all: FeedEntry[], limit: number, clock: Clock, now: number): FeedPage {
  const shown: FeedEntry[] = [];
  let n = 0;
  let i = 0;
  for (; i < all.length && n < limit; i++) {
    shown.push(all[i]!);
    n += all[i]!.members.length;
  }
  const days: FeedDay[] = bucketByDay(shown, (e) => e.time, clock, now).map((b) => ({
    key: b.key,
    label: b.label,
    entries: b.items,
    runs: b.items.reduce((sum, e) => sum + e.members.length, 0),
  }));
  return { days, shown, rest: all.slice(i), runsShown: n };
}

export interface FlatRow {
  key: string;
  kind: 'run' | 'fold' | 'member';
  run: FeedRow;
  entry: FeedEntry;
}

export function flat(shown: FeedEntry[], expanded: Readonly<Record<string, boolean>>): FlatRow[] {
  const out: FlatRow[] = [];
  for (const e of shown) {
    out.push({ key: e.key, kind: e.type === 'fold' ? 'fold' : 'run', run: e.run, entry: e });
    if (e.type === 'fold' && expanded[e.key]) for (const m of e.members) out.push({ key: `m:${m.run_id}`, kind: 'member', run: m, entry: e });
  }
  return out;
}

export function indexOf(rows: FlatRow[], runId: string, expanded: Readonly<Record<string, boolean>>): number {
  return rows.findIndex((x) =>
    x.kind === 'member' || x.kind === 'run' ? x.run.run_id === runId : x.entry.members.some((m) => m.run_id === runId) && !expanded[x.key],
  );
}

export function firstPick(rows: FlatRow[], info: Map<string, RunInfo>, unread: (r: FeedRow) => boolean): FlatRow | null {
  return rows.find((x) => changed(info, x.run) && unread(x.run)) ?? rows[0] ?? null;
}

export function walkRows(rows: FlatRow[], from: number, dir: 1 | -1, pred: (x: FlatRow) => boolean): number {
  for (let j = from + dir; j >= 0 && j < rows.length; j += dir) if (pred(rows[j]!)) return j;
  return -1;
}

export function nextUnread(rows: FlatRow[], from: number, pred: (x: FlatRow) => boolean): { index: number; wrapped: boolean } | null {
  const fwd = walkRows(rows, from, 1, pred);
  if (fwd >= 0) return { index: fwd, wrapped: false };
  for (let j = 0; j <= from && j < rows.length; j++) if (pred(rows[j]!)) return { index: j, wrapped: true };
  return null;
}

export function lateBy(run: { slot_at: number | null; started_at: number | null }): number | null {
  return run.slot_at != null && run.started_at != null ? Math.max(0, run.started_at - run.slot_at) : null;
}
