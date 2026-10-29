import { t } from '../../i18n/index.svelte';
import { ECHO_KEYS, isEmpty, isObj, isScalar, normalizeSlot, payload } from './diff';
import { isMarkdown, stripAnsi } from './markdown';
import { wordKind, type WordKind } from './marks';
import { REPORT_NEAR_CAP_BYTES } from './report-cap';
import { firstMetric, metricIn } from './signals';
import type { ReportSlot } from './types';
import { bytesWords, type Clock, countWords, fmtNum, humanKey, reasonWords, skipReason, skipSentence, tileLabel } from './words';

type Json = unknown;
type Obj = Record<string, Json>;

export interface FaceRun {
  status: string;
  reason: string | null;
  error: string | null;
  started_at: number | null;
  skip_count: number | null;
  first_slot_at?: number | null;
  last_slot_at?: number | null;
  has_report?: boolean;
  report_bytes?: number | null;
}

export interface RuleContext {
  clock: Clock;
  tz: string;
  now: number;
  prevReport?: Json;
}


export interface Change {
  kind: 'new' | 'same' | 'up' | 'down' | 'none';
  pct?: number | null;
  text: string;
}

export function changeOf(prev: Json, cur: number, key: string, unit?: string | null): Change {
  if (typeof prev !== 'number') return { kind: 'new', text: t('automations.page.change.new') };
  if (prev === cur) return { kind: 'same', text: t('automations.page.change.same') };
  const d = Math.round((cur - prev) * 1e6) / 1e6;
  const pct = prev ? Math.round((d / Math.abs(prev)) * 100) : null;
  return { kind: d > 0 ? 'up' : 'down', pct, text: `${d > 0 ? '+' : '-'}${fmtNum(Math.abs(d), key, unit)}${pct != null ? ` (${pct > 0 ? '+' : ''}${pct}%)` : ''}` };
}

export interface Tile {
  key: string;
  label: string;
  value: number;
  text: string;
  change: Change['kind'];
  changeText: string;
  top?: boolean;
}

const ID_KEY = /(^|_)(id|uuid)$/i;

export function metricTiles(report: Json, prevReport: Json): Tile[] {
  if (!isObj(report)) return [];
  const out: Tile[] = [];
  const seen = new Set<string>();
  const prevMetrics = isObj(prevReport) && Array.isArray(prevReport.metrics) ? (prevReport.metrics as { key?: string; label?: string; value?: unknown }[]) : [];
  const hasPrev = prevReport !== null && prevReport !== undefined;
  const none: Change = { kind: 'none', text: '' };
  const metrics = Array.isArray(report.metrics) ? (report.metrics as { key?: string; label?: string; value?: unknown; unit?: string }[]) : [];
  for (const m of metrics) {
    if (!m || typeof m.value !== 'number') continue;
    const key = m.key || m.label || '';
    const pm = prevMetrics.find((x) => (x.key || x.label) === key);
    seen.add(key);
    const ch = hasPrev ? changeOf(pm?.value, m.value, key, m.unit) : none;
    out.push({ key, label: m.label || tileLabel(key), value: m.value, text: fmtNum(m.value, key, m.unit), change: ch.kind, changeText: ch.text });
  }
  for (const k of Object.keys(report)) {
    const v = report[k];
    if (ECHO_KEYS[k] || ID_KEY.test(k) || k === 'metrics' || seen.has(k) || typeof v !== 'number' || !Number.isFinite(v)) continue;
    const ch = hasPrev ? changeOf(isObj(prevReport) ? prevReport[k] : undefined, v, k) : none;
    out.push({ key: k, label: tileLabel(k), value: v, text: fmtNum(v, k), change: ch.kind, changeText: ch.text, top: true });
  }
  return out.slice(0, 8);
}


export function unionKeys(list: Obj[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const o of list) {
    for (const k of Object.keys(o)) {
      if (!seen.has(k)) {
        seen.add(k);
        out.push(k);
      }
    }
  }
  return out;
}

export function likeKeys(list: Json[]): list is Obj[] {
  if (!list.length || !list.every(isObj)) return false;
  const objs = list as Obj[];
  const u = unionKeys(objs);
  return u.length > 0 && u.length <= 12 && objs.every((o) => Object.keys(o).length * 2 >= u.length);
}

export function sameKeys(list: Json[]): boolean {
  if (!list.length) return false;
  const k0 = isObj(list[0]) ? Object.keys(list[0]).sort().join('\u0001') : null;
  return k0 !== null && list.every((o) => isObj(o) && Object.keys(o).sort().join('\u0001') === k0);
}

export function statusKey(rows: Obj[], keys: string[]): string | undefined {
  return keys.find((k) => {
    let seen = false;
    const ok = rows.every((r) => {
      const v = r[k];
      if (v === null || v === undefined) return true;
      if (!wordKind(v)) return false;
      seen = true;
      return true;
    });
    return ok && seen;
  });
}

const KIND_ORDER: Record<WordKind, number> = { ok: 0, warn: 1, fail: 2 };

export interface NotOkRow {
  name: string | null;
  word: string;
  kind: WordKind;
  text: string;
}

export interface RowsSummary {
  keys: string[];
  statusKey: string | null;
  tally: { word: string; count: number }[];
  notOk: NotOkRow[];
  notOkMore: number;
  columns: string;
  showLabel: string;
}

export function rowsSummary(rows: Obj[]): RowsSummary {
  const keys = unionKeys(rows).filter((k) => k !== 'fix_prompt' && k !== '__k');
  const sk = statusKey(rows, keys) ?? null;
  const showLabel = t(rows.length === 1 ? 'automations.page.rows.show_one' : 'automations.page.rows.show', { n: rows.length });
  if (!sk) {
    const names = keys.slice(0, 6).map(humanKey).join(', ') + (keys.length > 6 ? `, +${keys.length - 6}` : '');
    return { keys, statusKey: null, tally: [], notOk: [], notOkMore: 0, columns: names, showLabel };
  }
  const counts = new Map<string, number>();
  for (const r of rows) {
    const v = r[sk];
    if (v === null || v === undefined) continue;
    const w = String(v).trim().toLowerCase();
    counts.set(w, (counts.get(w) ?? 0) + 1);
  }
  const kind = (w: string) => wordKind(w) ?? 'ok';
  const tally = [...counts.entries()]
    .map(([word, count]) => ({ word, count }))
    .sort((a, b) => KIND_ORDER[kind(a.word)] - KIND_ORDER[kind(b.word)]);
  const nameKey = keys.find(
    (k) => k !== sk && rows.every((r) => r[k] === null || r[k] === undefined || typeof r[k] === 'string') && rows.some((r) => typeof r[k] === 'string' && r[k]),
  );
  const bad = rows.filter((r) => r[sk] != null && wordKind(r[sk]) !== 'ok');
  const notOk: NotOkRow[] = bad.slice(0, 8).map((r) => ({
    name: nameKey && r[nameKey] ? String(r[nameKey]) : null,
    word: String(r[sk]).trim().toLowerCase(),
    kind: wordKind(r[sk]) as WordKind,
    text: keys
      .filter((k) => k !== sk && k !== nameKey && typeof r[k] === 'string' && r[k])
      .map((k) => String(r[k]).slice(0, 120))
      .join(' '),
  }));
  return { keys, statusKey: sk, tally, notOk, notOkMore: Math.max(0, bad.length - 8), columns: '', showLabel };
}


export interface StringShape {
  blank: boolean;
  text: string;
  markdown: boolean;
  long: boolean;
  head: string[];
  tail: string[];
  cut: number;
  lineCount: number;
}

export function stringShape(raw: string): StringShape {
  const text = stripAnsi(raw);
  const lines = text.split('\n');
  const long = lines.length > 40 || text.length > 4096;
  return {
    blank: !text.trim(),
    text,
    markdown: isMarkdown(text),
    long,
    head: long ? lines.slice(0, 12) : lines,
    tail: long ? lines.slice(-3) : [],
    cut: long ? Math.max(0, lines.length - 15) : 0,
    lineCount: lines.length,
  };
}


const STATUS_ORDER = ['fail', 'warn', 'raised', 'ok'] as const;
const WORD_CLASS: Record<string, (typeof STATUS_ORDER)[number]> = { fail: 'fail', failed: 'fail', error: 'fail', warn: 'warn', raised: 'raised', ok: 'ok', pass: 'ok', passed: 'ok', healthy: 'ok' };

function leaves(v: Json, out: Json[] = []): Json[] {
  if (isScalar(v)) {
    out.push(v);
    return out;
  }
  for (const x of Array.isArray(v) ? v : Object.values(v as Obj)) leaves(x, out);
  return out;
}

export function countSentence(v: Json): string | null {
  const c: Record<string, number> = {};
  let n = 0;
  for (const x of leaves(v)) {
    const k = typeof x === 'string' ? WORD_CLASS[x.trim().toLowerCase()] : undefined;
    if (k) {
      c[k] = (c[k] ?? 0) + 1;
      n++;
    }
  }
  if (!n) return null;
  return STATUS_ORDER.filter((k) => c[k]).map((k) => `${c[k]} ${k}`).join(', ');
}

function plain(s: string): string {
  return s.replace(/^(#{1,6}\s+|[-*]\s+|\d+\.\s+)/, '');
}

export function firstLine(s: string): string {
  const l = stripAnsi(s)
    .split('\n')
    .find((x) => x.trim());
  return l ? l.trim() : '';
}

function firstString(v: Json): string | null {
  if (typeof v === 'string') return v.trim() ? v : null;
  if (v && typeof v === 'object') {
    for (const x of Array.isArray(v) ? v : Object.values(v as Obj)) {
      const f = firstString(x);
      if (f !== null) return f;
    }
  }
  return null;
}

export type FaceRule = 'status' | 'reason' | 'report' | 'exit_code' | 'error' | 'nothing' | 'summary' | 'items' | 'status_words' | 'text' | 'number' | 'fields' | 'pending' | 'cleared';

export interface Face {
  text: string;
  rule: FaceRule;
}

export function face(run: FaceRun, rawSlot: ReportSlot, ctx: RuleContext): Face {
  const slot = normalizeSlot(rawSlot);
  const s = run.status;
  const rel = ctx.clock.rel(run.started_at, ctx.now);
  if (s === 'running') return { text: t('automations.page.face.running', { rel }), rule: 'status' };
  if (s === 'claimed') return { text: t('automations.page.face.starting'), rule: 'status' };
  if (s === 'waiting_on_you') {
    return { text: run.reason ? t('automations.page.face.waiting_reason', { reason: reasonWords(run.reason) }) : t('automations.page.face.waiting_since', { rel }), rule: 'status' };
  }
  if (s === 'skipped') return { text: skipSentence(run, ctx.tz), rule: 'reason' };
  if (slot.state === 'pending') return { text: t('automations.page.face.loading'), rule: 'pending' };
  if (slot.state === 'unreadable' && slot.reason === 'read_failed') return { text: t('automations.page.face.unreadable'), rule: 'report' };
  if (slot.state === 'unreadable' && s !== 'failed') return { text: t('automations.page.report.cleared'), rule: 'cleared' };
  const rep = slot.state === 'ready' ? slot.report : undefined;
  if (s === 'failed') {
    if (isObj(rep) && typeof rep.exit_code === 'number') {
      const el = typeof rep.stderr_tail === 'string' ? firstLine(rep.stderr_tail) : '';
      return { text: `exit ${rep.exit_code}${el ? `: ${el}` : ''}`, rule: 'exit_code' };
    }
    if (run.error) return { text: firstLine(run.error), rule: 'error' };
    return { text: run.reason ? reasonWords(run.reason) : t('automations.page.face.failed'), rule: 'reason' };
  }
  const nothing: Face = { text: t('automations.page.face.nothing'), rule: 'nothing' };
  if (rep === null || rep === undefined) return nothing;
  if (isObj(rep)) {
    if (typeof rep.summary === 'string' && rep.summary.trim()) return { text: plain(firstLine(rep.summary)), rule: 'summary' };
    if (Array.isArray(rep.items)) {
      const ci = countSentence(rep.items);
      if (ci) return { text: ci, rule: 'items' };
    }
    for (const k of Object.keys(rep)) {
      const v = rep[k];
      if (v && typeof v === 'object') {
        const cs = countSentence(v);
        if (cs) return { text: cs, rule: 'status_words' };
      }
    }
    if (typeof rep.exit_code === 'number') {
      const ol = typeof rep.stdout_tail === 'string' ? firstLine(rep.stdout_tail) : '';
      return { text: `exit ${rep.exit_code}, ${ol || t('automations.page.face.no_output')}`, rule: 'exit_code' };
    }
    const doc = Object.keys(rep).find((k) => typeof rep[k] === 'string' && (rep[k] as string).includes('\n') && (rep[k] as string).trim() && !ECHO_KEYS[k] && k !== 'stdout_tail' && k !== 'stderr_tail');
    if (doc) return { text: plain(firstLine(rep[doc] as string)).slice(0, 120), rule: 'text' };
    const m = firstMetric(rep);
    if (m) {
      const pm = ctx.prevReport === undefined || ctx.prevReport === null ? null : metricIn(ctx.prevReport, m);
      const ch = typeof pm === 'number' && pm !== m.value ? changeOf(pm, m.value, m.key, m.unit) : null;
      const pc = ch ? (ch.pct == null ? ch.text : ch.pct === 0 ? `${ch.kind === 'up' ? '+' : '-'}<1%` : `${ch.pct > 0 ? '+' : ''}${ch.pct}%`) : null;
      return { text: `${m.label} ${fmtNum(m.value, m.key, m.unit)}${pc ? ` (${pc})` : ''}`, rule: 'number' };
    }
    const body = payload(rep) as Obj;
    const top = Object.keys(body).find((k) => typeof rep[k] === 'string' && (rep[k] as string).trim());
    const fs = top ? (rep[top] as string) : firstString(body);
    if (fs) {
      const one = firstLine(fs);
      return { text: top && fs.length <= 40 && !fs.includes('\n') ? `${humanKey(top)} ${one}` : plain(one).slice(0, 120), rule: 'text' };
    }
    if (Object.keys(rep).length && !isEmpty(rep)) return { text: countWords('automations.page.count.field', Object.keys(rep).length), rule: 'fields' };
    return nothing;
  }
  if (typeof rep === 'string' && rep.trim()) return { text: firstLine(rep).slice(0, 120), rule: 'text' };
  if (Array.isArray(rep) && rep.length) return { text: countWords('automations.page.count.item', rep.length), rule: 'fields' };
  return nothing;
}


export interface EmptyStatement {
  text: string;
  facts: string[];
}

export function emptyStatement(run: FaceRun, report: Json, took: string | null, sessions: number, ctx: RuleContext): EmptyStatement {
  const facts: string[] = [];
  if (took) facts.push(t('automations.page.empty.took', { took }));
  if (isObj(report) && typeof report.exit_code === 'number') facts.push(t('automations.page.empty.exit', { n: report.exit_code }));
  if (sessions) facts.push(countWords('automations.page.count.session', sessions));
  const s = run.status;
  const rel = ctx.clock.rel(run.started_at, ctx.now);
  let text: string;
  if (s === 'skipped') text = t('automations.page.empty.skipped', { reason: skipReason(run, ctx.tz) });
  else if (s === 'failed') text = run.error ? t('automations.page.empty.failed_error', { error: run.error }) : run.reason ? t('automations.page.empty.failed_reason', { reason: reasonWords(run.reason) }) : t('automations.page.empty.failed');
  else if (s === 'running') text = t('automations.page.empty.running', { rel });
  else if (s === 'claimed') text = t('automations.page.face.starting');
  else if (s === 'waiting_on_you') text = t('automations.page.empty.waiting', { rel });
  else {
    text = t('automations.page.face.nothing');
    if (run.has_report && run.report_bytes === 0) facts.push(t('automations.page.empty.zero_bytes'));
    else if (!run.has_report) facts.push(t('automations.page.empty.no_report'));
  }
  return { text, facts };
}


export type BodySection =
  | { kind: 'summary'; text: string }
  | { kind: 'exit_code'; code: number; zero: boolean }
  | { kind: 'tiles'; tiles: Tile[] }
  | { kind: 'stream'; name: 'stderr' | 'stdout'; text: string }
  | { kind: 'quiet' }
  | { kind: 'items'; items: { status: unknown; label: string; detail: string; fix_prompt: string | null }[] }
  | { kind: 'fields'; fields: Obj }
  | { kind: 'section'; key: string; heading: string; count: number | null; value: Json }
  | { kind: 'cap'; note: string };

export function conversationUuid(report: Json): string | null {
  return isObj(report) && typeof report.conversation_uuid === 'string' && report.conversation_uuid ? report.conversation_uuid : null;
}

export function bodyPlan(run: { status: string; report_bytes: number | null }, report: Obj, prevReport: Json): BodySection[] {
  const h: BodySection[] = [];
  const done = new Set<string>(['metrics']);
  if (typeof report.summary === 'string' && report.summary.trim()) {
    h.push({ kind: 'summary', text: report.summary });
    done.add('summary');
  }
  if (typeof report.exit_code === 'number') {
    h.push({ kind: 'exit_code', code: report.exit_code, zero: report.exit_code === 0 });
    done.add('exit_code');
  }
  const tiles = metricTiles(report, prevReport);
  for (const x of tiles) if (x.top) done.add(x.key);
  if (tiles.length) h.push({ kind: 'tiles', tiles });
  if (typeof report.stdout_tail === 'string' || typeof report.stderr_tail === 'string') {
    const streams: ['stderr' | 'stdout', Json][] = [['stderr', report.stderr_tail], ['stdout', report.stdout_tail]];
    if (run.status !== 'failed') streams.reverse();
    let shown = false;
    for (const [name, v] of streams) {
      if (typeof v === 'string' && v.trim()) {
        shown = true;
        h.push({ kind: 'stream', name, text: v });
      }
    }
    if (!shown) h.push({ kind: 'quiet' });
    done.add('stdout_tail');
    done.add('stderr_tail');
  }
  if (Array.isArray(report.items) && report.items.length && report.items.every(isObj)) {
    h.push({
      kind: 'items',
      items: (report.items as Obj[]).map((it) => ({
        status: it.status,
        label: it.label == null ? '' : String(it.label),
        detail: it.detail ? String(it.detail) : '',
        fix_prompt: typeof it.fix_prompt === 'string' ? it.fix_prompt : null,
      })),
    });
    done.add('items');
  }
  const keys = Object.keys(report).filter((k) => !done.has(k) && !ECHO_KEYS[k] && k !== 'fix_prompt' && k !== 'conversation_uuid');
  const small: Obj = {};
  const rest: string[] = [];
  for (const k of keys) {
    const v = report[k];
    if (isScalar(v) && !(typeof v === 'string' && (v.includes('\n') || v.length > 120))) small[k] = v;
    else rest.push(k);
  }
  if (report.conversation_uuid) small.conversation_uuid = report.conversation_uuid;
  if (Object.keys(small).length) h.push({ kind: 'fields', fields: small });
  for (const k of rest) {
    const v = report[k];
    const n = Array.isArray(v) ? v.length : isObj(v) ? Object.keys(v).length : null;
    h.push({ kind: 'section', key: k, heading: humanKey(k), count: n, value: v });
  }
  if (!h.length || (isEmpty(report) && !tiles.length)) return [];
  if ((run.report_bytes ?? 0) >= REPORT_NEAR_CAP_BYTES) h.push({ kind: 'cap', note: t('automations.page.report.cap', { size: bytesWords(run.report_bytes) }) });
  return h;
}
