import { t } from '../../i18n/index.svelte';
import type { Automation, SessionChoice } from '../api';
import { isObj, isScalar, payload, usableReport, ECHO_KEYS } from '../logic/diff';
import {
  analyse,
  changed,
  entries,
  flat,
  haystack,
  isUnread,
  lateBy,
  page,
  slotOf,
  type FeedEntry,
  type FeedPage,
  type FeedRow,
  type FlatRow,
  type RunInfo,
  type UnreadState,
} from '../logic/feed';
import { countSentence, face, firstLine, metricTiles, type Face, type RuleContext } from '../logic/report-rules';
import type { FeedRun, ReportLookup } from '../logic/types';
import { bytesWords, humanKey, isLive, secsWords, statusWord, tookWords, triggerLabel, triggerWord, type Clock } from '../logic/words';
import { stripAnsi } from '../logic/markdown';

const INDENT = '  ';

export interface ModelInput {
  runs: FeedRun[];
  older: FeedRun[];
  lookup: ReportLookup;
  q: string;
  changedOnly: boolean;
  unreadOnly: boolean;
  unread: UnreadState;
  clock: Clock;
  tz: string;
  now: number;
  limit: number;
  expanded: Readonly<Record<string, boolean>>;
  retryMax: (automationId: string) => number;
}

export interface FeedModel {
  info: Map<string, RunInfo>;
  visible: FeedRow[];
  all: FeedEntry[];
  pg: FeedPage;
  rows: FlatRow[];
  counts: { runs: number; changed: number; unread: number };
  unread: (run: FeedRow) => boolean;
  faceOf: (run: FeedRow) => Face;
}

export function buildModel(i: ModelInput): FeedModel {
  const rows = i.runs as FeedRow[];
  const info = analyse(rows, i.older as FeedRow[], i.lookup);
  const unread = (run: FeedRow): boolean => isUnread(run, i.unread, i.now);
  const faceOf = (run: FeedRow): Face => {
    const pred = info.get(run.run_id)?.pred;
    const prevReport = pred ? (usableReport(slotOf(pred, i.lookup)) ?? null) : null;
    const ctx: RuleContext = { clock: i.clock, tz: i.tz, now: i.now, prevReport };
    return face(run, slotOf(run, i.lookup), ctx);
  };
  const q = i.q.trim().toLowerCase();
  const visible = rows.filter(
    (r) =>
      (!q || haystack(r, slotOf(r, i.lookup), { clock: i.clock, tz: i.tz, now: i.now }, i.retryMax(r.automation_id)).includes(q)) &&
      (!i.changedOnly || changed(info, r)) &&
      (!i.unreadOnly || unread(r)),
  );
  const all = entries(visible, info, i.changedOnly, i.clock);
  const pg = page(all, i.limit, i.clock, i.now);
  return {
    info,
    visible,
    all,
    pg,
    rows: flat(pg.shown, i.expanded),
    counts: {
      runs: all.reduce((n, e) => n + e.members.length, 0),
      changed: all.filter((e) => e.type === 'run' && changed(info, e.run)).length,
      unread: visible.filter(unread).length,
    },
    unread,
    faceOf,
  };
}

export function isChangedRow(model: FeedModel, x: FlatRow): boolean {
  return x.kind === 'run' && changed(model.info, x.run);
}

export function isUnreadRow(model: FeedModel, x: FlatRow): boolean {
  return x.kind === 'fold' ? x.entry.members.some(model.unread) : model.unread(x.run);
}

export function dayChanged(day: { entries: FeedEntry[] }, info: Map<string, RunInfo>): number {
  return day.entries.filter((e) => e.type === 'run' && changed(info, e.run)).length;
}


export const STATUS_OPTIONS = ['succeeded', 'failed', 'skipped', 'running', 'claimed', 'waiting_on_you'] as const;
export const TRIGGER_OPTIONS = ['schedule', 'run_now', 'retry', 'catch_up'] as const;

export interface Opt {
  value: string;
  label: string;
}

export function statusOptions(): Opt[] {
  return STATUS_OPTIONS.map((s) => ({ value: s, label: statusWord(s) }));
}

export function triggerOptions(): Opt[] {
  return TRIGGER_OPTIONS.map((k) => ({ value: k, label: triggerLabel(k) }));
}

export function automationOptions(autos: readonly Automation[]): Opt[] {
  return autos
    .map((a) => ({ value: a.automation_id, label: a.name }))
    .sort((a, b) => (a.label.toLowerCase() < b.label.toLowerCase() ? -1 : a.label.toLowerCase() > b.label.toLowerCase() ? 1 : 0));
}

export function whereOptions(autos: readonly Automation[], projects: readonly { id: number | null; name: string }[], sessions: readonly SessionChoice[]): Opt[] {
  const sessionName = (uuid: string): string => sessions.find((s) => s.session_uuid === uuid)?.label ?? uuid;
  const byProject = new Map<number, Set<string>>();
  let unassigned = false;
  for (const a of autos) {
    const f = a.files_under;
    if (!f || (f.project_id == null && f.session_uuid == null)) {
      unassigned = true;
      continue;
    }
    if (f.project_id == null) {
      unassigned = true;
      continue;
    }
    const set = byProject.get(f.project_id) ?? new Set<string>();
    if (f.session_uuid) set.add(f.session_uuid);
    byProject.set(f.project_id, set);
  }
  const out: Opt[] = [];
  const named = [...byProject.keys()]
    .map((id) => ({ id, name: projects.find((p) => p.id === id)?.name ?? String(id) }))
    .sort((a, b) => (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1));
  for (const p of named) {
    out.push({ value: `p:${p.id}`, label: p.name });
    for (const uuid of [...(byProject.get(p.id) ?? [])].sort()) out.push({ value: `s:${uuid}`, label: INDENT + sessionName(uuid) });
  }
  for (const a of autos) {
    const f = a.files_under;
    if (f?.session_uuid && f.project_id == null && !out.some((o) => o.value === `s:${f.session_uuid}`)) out.push({ value: `s:${f.session_uuid}`, label: sessionName(f.session_uuid) });
  }
  if (unassigned) out.push({ value: 'u', label: t('automations.page.feed.unassigned') });
  return out;
}

export function whereWords(a: Automation | undefined, projects: readonly { id: number | null; name: string }[], sessions: readonly SessionChoice[]): string {
  const f = a?.files_under;
  if (f?.session_uuid) return sessions.find((s) => s.session_uuid === f.session_uuid)?.label ?? f.session_uuid;
  if (f?.project_id != null) return projects.find((p) => p.id === f.project_id)?.name ?? String(f.project_id);
  return t('automations.page.feed.unassigned');
}


export function dayCase(epoch: number, tz: string): string {
  return new Intl.DateTimeFormat('en-US', { timeZone: tz, month: 'short', day: 'numeric' }).format(new Date(epoch * 1000));
}

export function dayOf(epoch: number, tz: string): string {
  return dayCase(epoch, tz).toLowerCase();
}

export interface ReaderRun extends FeedRow {
  number: number;
  cost_usd: number | null;
  notes?: { by?: { kind?: string; name?: string } | null; [field: string]: unknown } | null;
  sessions?: unknown[] | null;
}

export function readerFacts(run: ReaderRun, clock: Clock, tz: string, retryMax: number, cost: string): [string, string][] {
  const f: [string, string][] = [];
  if (run.slot_at != null) f.push(['slot', `${dayCase(run.slot_at, tz)} ${clock.hms24(run.slot_at)}`]);
  if (run.started_at != null) f.push(['started', `${dayCase(run.started_at, tz)} ${clock.hms24(run.started_at)}`]);
  const late = lateBy(run);
  if (late != null) f.push(['late_by', late < 0.05 ? t('automations.page.reader.late_under') : secsWords(late)]);
  f.push(['took', tookWords(run) || (isLive(run.status) ? t('automations.page.reader.not_finished') : t('automations.page.reader.no_timing'))]);
  const by = run.notes?.by?.name;
  const word = triggerWord(run, retryMax) || triggerLabel('schedule');
  f.push(['trigger', by ? t('automations.page.reader.pressed_by', { trigger: word, name: by }) : word]);
  if ((run.attempt ?? 1) > 1) f.push(['attempt', t('automations.page.reader.attempt_of', { n: run.attempt ?? 1, total: retryMax + 1 })]);
  f.push(['computer', run.host || t('automations.page.reader.computer_not_recorded')]);
  f.push(['cost', cost]);
  const bytes = run.report_bytes ?? 0;
  f.push([
    'size',
    bytes > 0
      ? bytes >= 524288
        ? t('automations.page.reader.size_cap', { size: bytesWords(bytes) })
        : bytesWords(bytes)
      : run.status === 'succeeded'
        ? run.has_report
          ? t('automations.page.reader.size_zero')
          : t('automations.page.reader.size_none_stored')
        : t('automations.page.reader.size_none'),
  ]);
  if (run.sessions && run.sessions.length) f.push(['sessions', String(run.sessions.length)]);
  return f;
}

export interface WhatRan {
  kind: string;
  text: string;
  params: [string, string][];
}

export function whatRan(target: { kind: string; [field: string]: unknown }, kindLabel: string): WhatRan {
  const main = ['prompt', 'command', 'title', 'text', 'blueprint', 'recipe', 'name'].find((k) => typeof target[k] === 'string' && target[k] !== '');
  const params: [string, string][] = [];
  for (const [k, v] of Object.entries(target)) {
    if (k === 'kind' || k === main) continue;
    if (k === 'steps' && Array.isArray(v)) {
      params.push([humanKey(k), v.map((s) => String((s as { label?: string; kind?: string }).label || (s as { kind?: string }).kind || '')).filter(Boolean).join(', ')]);
    } else if ((typeof v === 'string' && v !== '') || typeof v === 'number' || typeof v === 'boolean') params.push([humanKey(k), String(v)]);
  }
  return { kind: kindLabel, text: main ? String(target[main]) : '', params };
}


function firstText(v: unknown): string | null {
  if (typeof v === 'string') return v.trim() ? v : null;
  if (v && typeof v === 'object') {
    for (const x of Array.isArray(v) ? v : Object.values(v as Record<string, unknown>)) {
      const found = firstText(x);
      if (found !== null) return found;
    }
  }
  return null;
}

export function compactLines(run: { status: string; error: string | null }, faceText: string, report: unknown, prevReport: unknown, lines = 2): string[] {
  const out: string[] = [];
  const add = (s: string | null | undefined): void => {
    if (s && !out.includes(s)) out.push(s);
  };
  if (run.status !== 'succeeded' || !isObj(report)) {
    add(faceText);
    if (run.error) add(firstLine(run.error));
    return out.slice(0, lines);
  }
  if (run.error) add(firstLine(run.error));
  for (const tile of metricTiles(report, prevReport ?? null).slice(0, 3)) add(`${tile.label} ${tile.text}${tile.changeText && tile.change !== 'none' ? ` ${tile.changeText}` : ''}`);
  let tally = Array.isArray(report.items) ? countSentence(report.items) : null;
  if (!tally) {
    for (const v of Object.values(report)) {
      if (v && typeof v === 'object') {
        tally = countSentence(v);
        if (tally) break;
      }
    }
  }
  add(tally);
  if (typeof report.summary === 'string') add(firstLine(report.summary));
  const text = firstText(payload(report));
  if (text)
    stripAnsi(text)
      .split('\n')
      .filter((x) => x.trim())
      .slice(0, 3)
      .forEach((l) => add(l.trim().slice(0, 140)));
  Object.keys(report)
    .filter((k) => !ECHO_KEYS[k] && isScalar(report[k]) && typeof report[k] !== 'number' && !(typeof report[k] === 'string' && (report[k] as string).includes('\n')))
    .slice(0, 4)
    .forEach((k) => add(`${humanKey(k)} ${String(report[k] ?? 'none').slice(0, 80)}`));
  if (!out.length) add(faceText);
  return out.slice(0, lines);
}


export interface Seen {
  counts: Record<string, number>;
  ids: Record<string, true>;
  newest: number;
}

export interface RowChanges {
  entering: Record<string, true>;
  ticked: Record<string, true>;
  seen: Seen;
}

export function rowChanges(prev: Seen | null, shown: FeedEntry[]): RowChanges {
  const counts: Record<string, number> = {};
  const ids: Record<string, true> = {};
  const entering: Record<string, true> = {};
  const ticked: Record<string, true> = {};
  for (const e of shown) {
    counts[e.key] = e.members.length;
    for (const m of e.members) ids[m.run_id] = true;
    if (!prev) continue;
    const known = prev.counts[e.key] !== undefined;
    if (e.type === 'fold') {
      const before = e.members.some((m) => prev.ids[m.run_id]);
      if (known ? prev.counts[e.key] !== e.members.length : before) ticked[e.key] = true;
      else if (!known && e.time > prev.newest) entering[e.key] = true;
    } else if (!known && !prev.ids[e.run.run_id] && e.time > prev.newest) entering[e.key] = true;
  }
  const newest = shown.length ? Math.max(...shown.map((e) => e.time)) : (prev?.newest ?? 0);
  return { entering, ticked, seen: { counts, ids, newest } };
}
