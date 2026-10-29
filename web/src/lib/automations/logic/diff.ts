import { t } from '../../i18n/index.svelte';
import type { ReportSlot } from './types';
import { bytesWords, pathWords, signed } from './words';

export const ECHO_KEYS: Readonly<Record<string, true>> = { command: true, exit_code: true, duration_s: true };

export const VOLATILE = /^(at|time|timestamp|id|run_id|duration|duration_s|started|ended)$|_at$/i;

type Json = unknown;
type Obj = Record<string, Json>;

export function isObj(v: Json): v is Obj {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

export function isScalar(v: Json): boolean {
  return v === null || typeof v !== 'object';
}

function isText(v: Json): v is string {
  return typeof v === 'string' && (v.includes('\n') || v.length > 200);
}

function lastSegment(path: string): string {
  const m = /([^.[\]]+)\]?$/.exec(path);
  return m?.[1] ?? path;
}

export function payload(report: Json): Json {
  if (!isObj(report)) return report;
  const out: Obj = {};
  for (const k of Object.keys(report)) if (!ECHO_KEYS[k]) out[k] = report[k];
  return out;
}

function emptyVal(v: Json): boolean {
  if (v === null || v === undefined) return true;
  if (typeof v === 'string') return !v.trim();
  if (Array.isArray(v)) return v.every(emptyVal);
  if (isObj(v)) return Object.keys(v).every((k) => emptyVal(v[k]));
  return false;
}

export function isEmpty(report: Json): boolean {
  if (report === null || report === undefined) return true;
  return emptyVal(payload(report));
}

/* report cleared to save space */
export function isPrunedReport(report: Json): boolean {
  return isObj(report) && report.pruned === true && Object.keys(report).length === 1;
}

export function normalizeSlot(slot: ReportSlot): ReportSlot {
  return slot.state === 'ready' && isPrunedReport(slot.report) ? { state: 'unreadable', reason: 'pruned' } : slot;
}

export function usableReport(slot: ReportSlot): Json | undefined {
  const s = normalizeSlot(slot);
  return s.state === 'ready' && s.report !== null && s.report !== undefined ? s.report : undefined;
}

export function stable(v: Json): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(',')}]`;
  if (isObj(v)) {
    return `{${Object.keys(v)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${stable(v[k])}`)
      .join(',')}}`;
  }
  return JSON.stringify(v) ?? 'null';
}

export interface LineOp {
  t: '+' | '-';
  line: string;
}
export interface LineDiff {
  added: string[];
  removed: string[];
  ops: LineOp[];
}

export function lineDiff(a: string, b: string): LineDiff {
  const A = String(a).split('\n');
  const B = String(b).split('\n');
  const ops: LineOp[] = [];
  if (A.length > 500 || B.length > 500) {
    const sa: Record<string, number> = {};
    const sb: Record<string, number> = {};
    for (const l of A) sa[l] = (sa[l] ?? 0) + 1;
    for (const l of B) sb[l] = (sb[l] ?? 0) + 1;
    for (const l of A) {
      if (!sb[l]) ops.push({ t: '-', line: l });
      else sb[l]--;
    }
    for (const l of B) {
      if (!sa[l]) ops.push({ t: '+', line: l });
      else sa[l]--;
    }
  } else {
    const n = A.length;
    const m = B.length;
    const L: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0));
    for (let x = n - 1; x >= 0; x--) {
      for (let y = m - 1; y >= 0; y--) {
        L[x]![y] = A[x] === B[y] ? L[x + 1]![y + 1]! + 1 : Math.max(L[x + 1]![y]!, L[x]![y + 1]!);
      }
    }
    let p = 0;
    let q = 0;
    while (p < n && q < m) {
      if (A[p] === B[q]) {
        p++;
        q++;
      } else if (L[p + 1]![q]! >= L[p]![q + 1]!) ops.push({ t: '-', line: A[p++]! });
      else ops.push({ t: '+', line: B[q++]! });
    }
    while (p < n) ops.push({ t: '-', line: A[p++]! });
    while (q < m) ops.push({ t: '+', line: B[q++]! });
  }
  return {
    added: ops.filter((o) => o.t === '+').map((o) => o.line),
    removed: ops.filter((o) => o.t === '-').map((o) => o.line),
    ops,
  };
}

export interface DiffEntry {
  kind: 'appeared' | 'cleared' | 'number' | 'string' | 'text';
  path: string;
  label: string;
  value?: Json;
  old?: Json;
  new?: Json;
  delta?: number;
  pct?: number | null;
  lines?: LineDiff;
}

function keyField(arr: Json[]): string | null {
  if (!arr.length || !arr.every(isObj)) return null;
  const first = Object.keys(arr[0] as Obj).filter((k) => typeof (arr[0] as Obj)[k] === 'string');
  for (const f of ['id', 'name', 'title', ...first]) {
    const seen = new Set<string>();
    let ok = true;
    for (const item of arr as Obj[]) {
      const v = item[f];
      if (typeof v !== 'string' && typeof v !== 'number') {
        ok = false;
        break;
      }
      if (seen.has(String(v))) {
        ok = false;
        break;
      }
      seen.add(String(v));
    }
    if (ok) return f;
  }
  return null;
}

function describe(v: Json): string {
  if (isScalar(v)) return String(v);
  if (Array.isArray(v)) return t('automations.page.diff.items', { n: v.length });
  const o = v as Obj;
  const keys = Object.keys(o);
  for (const k of keys) if (typeof o[k] === 'string' && (k === 'title' || k === 'name')) return o[k] as string;
  for (const k of keys) if (typeof o[k] === 'string') return o[k] as string;
  return t('automations.page.diff.fields', { n: keys.length });
}

interface WalkState {
  showAll: boolean;
  ignored: number;
}

function walk(a: Json, b: Json, path: string, out: DiffEntry[], st: WalkState): void {
  if (a === undefined && b === undefined) return;
  const volatile = !st.showAll && VOLATILE.test(lastSegment(path));
  if (a === undefined) {
    if (volatile) st.ignored++;
    else out.push({ kind: 'appeared', path, label: pathWords(path), value: b });
    return;
  }
  if (b === undefined) {
    if (volatile) st.ignored++;
    else out.push({ kind: 'cleared', path, label: pathWords(path), value: a });
    return;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    const fa = keyField(a);
    const fb = keyField(b);
    if ((a.length || b.length) && (fa || !a.length) && (fb || !b.length) && (a.length ? fa : fb) && (b.length ? fb : fa)) {
      const ma = new Map<string, Obj>();
      const mb = new Map<string, Obj>();
      for (const x of a as Obj[]) ma.set(String(x[fa as string]), x);
      for (const x of b as Obj[]) mb.set(String(x[fb as string]), x);
      const order: string[] = [...mb.keys()];
      for (const k of ma.keys()) if (!mb.has(k)) order.push(k);
      for (const k of order) {
        const p = `${path}[${k}]`;
        const xa = ma.get(k);
        const xb = mb.get(k);
        if (!xa) out.push({ kind: 'appeared', path: p, label: describe(xb), value: xb });
        else if (!xb) out.push({ kind: 'cleared', path: p, label: describe(xa), value: xa });
        else walk(xa, xb, p, out, st);
      }
      return;
    }
    if (a.every(isScalar) && b.every(isScalar)) {
      const sa = new Set(a.map(String));
      const sb = new Set(b.map(String));
      for (const v of b) if (!sa.has(String(v))) out.push({ kind: 'appeared', path: `${path}[${String(v)}]`, label: String(v), value: v });
      for (const v of a) if (!sb.has(String(v))) out.push({ kind: 'cleared', path: `${path}[${String(v)}]`, label: String(v), value: v });
      return;
    }
    const n = Math.max(a.length, b.length);
    for (let i = 0; i < n; i++) walk(a[i], b[i], `${path}[${i}]`, out, st);
    return;
  }
  if (isObj(a) && isObj(b)) {
    const keys: string[] = [...Object.keys(b)];
    for (const k of Object.keys(a)) if (!(k in b)) keys.push(k);
    for (const k of keys) walk(a[k], b[k], path ? `${path}.${k}` : k, out, st);
    return;
  }
  if (a === b) return;
  if (volatile) {
    st.ignored++;
    return;
  }
  if (typeof a === 'number' && typeof b === 'number') {
    const d = Math.round((b - a) * 1e6) / 1e6;
    out.push({ kind: 'number', path, label: pathWords(path), old: a, new: b, delta: d, pct: a ? (d / Math.abs(a)) * 100 : null });
    return;
  }
  if (typeof a === 'string' && typeof b === 'string' && (isText(a) || isText(b))) {
    out.push({ kind: 'text', path, label: pathWords(path), old: a, new: b, lines: lineDiff(a, b) });
    return;
  }
  out.push({ kind: 'string', path, label: pathWords(path), old: isScalar(a) ? a : describe(a), new: isScalar(b) ? b : describe(b) });
}

export interface DiffRun {
  run_id: string;
  number: number;
  status: string;
  started_at: number | null;
  ended_at: number | null;
  report_bytes: number | null;
  cost_usd: number | null;
}

export interface DiffSide {
  run: DiffRun;
  slot: ReportSlot;
}

export interface DiffGroups {
  appeared: DiffEntry[];
  cleared: DiffEntry[];
  numbers: DiffEntry[];
  numbersMore: number;
  strings: DiffEntry[];
  texts: DiffEntry[];
}

export interface DiffResult {
  first?: boolean;
  base: DiffRun | null;
  head: DiffRun;
  entries: DiffEntry[];
  groups: DiffGroups;
  deltas: { label: string; text: string }[];
  flip: string | null;
  ignored: number;
  noReport: boolean;
  counts: { appeared: number; cleared: number; numbers: number; strings: number; linesAdded: number; linesRemoved: number; total: number };
  sentence: string;
  same: boolean;
  hunks: DiffEntry[];
}

function emptyGroups(): DiffGroups {
  return { appeared: [], cleared: [], numbers: [], numbersMore: 0, strings: [], texts: [] };
}

export function firstResult(head: DiffRun): DiffResult {
  return {
    first: true,
    base: null,
    head,
    entries: [],
    groups: emptyGroups(),
    deltas: [],
    flip: null,
    ignored: 0,
    noReport: false,
    counts: { appeared: 0, cleared: 0, numbers: 0, strings: 0, linesAdded: 0, linesRemoved: 0, total: 0 },
    sentence: t('automations.page.diff.first'),
    same: false,
    hunks: [],
  };
}

export function compare(base: DiffSide, head: DiffSide, opts: { showAll?: boolean; statusWord: (s: string) => string }): DiffResult {
  const ra = usableReport(base.slot);
  const rb = usableReport(head.slot);
  const b = base.run;
  const h = head.run;
  const flip = b.status !== h.status ? t('automations.page.diff.flip', { base: opts.statusWord(b.status), head: opts.statusWord(h.status) }) : null;
  const deltas: { label: string; text: string }[] = [];
  if (b.started_at != null && b.ended_at != null && h.started_at != null && h.ended_at != null) {
    const dd = Math.round((h.ended_at - h.started_at - (b.ended_at - b.started_at)) * 10) / 10;
    if (dd) deltas.push({ label: t('automations.page.diff.delta.took'), text: signed(dd, ' s') });
  }
  if (b.report_bytes != null && h.report_bytes != null && b.report_bytes !== h.report_bytes) {
    const db = h.report_bytes - b.report_bytes;
    deltas.push({ label: t('automations.page.diff.delta.size'), text: `${db > 0 ? '+' : '-'}${bytesWords(Math.abs(db))}` });
  }
  if (b.cost_usd != null && h.cost_usd != null && b.cost_usd !== h.cost_usd) {
    const c = signed(Math.round((h.cost_usd - b.cost_usd) * 100) / 100, '').replace(/^([+-])/, '$1$$');
    deltas.push({ label: t('automations.page.diff.delta.cost'), text: c });
  }
  const entries: DiffEntry[] = [];
  const st: WalkState = { showAll: !!opts.showAll, ignored: 0 };
  const noReport = ra === undefined || rb === undefined;
  if (!noReport) walk(ra, rb, '', entries, st);
  const g = emptyGroups();
  for (const e of entries) {
    if (e.kind === 'appeared') g.appeared.push(e);
    else if (e.kind === 'cleared') g.cleared.push(e);
    else if (e.kind === 'number') g.numbers.push(e);
    else if (e.kind === 'string') g.strings.push(e);
    else g.texts.push(e);
  }
  g.numbers.sort(
    (x, y) =>
      (y.pct == null ? Infinity : Math.abs(y.pct)) - (x.pct == null ? Infinity : Math.abs(x.pct)) ||
      Math.abs(y.delta ?? 0) - Math.abs(x.delta ?? 0),
  );
  g.numbersMore = Math.max(0, g.numbers.length - 10);
  let la = 0;
  let lr = 0;
  for (const x of g.texts) {
    la += x.lines?.added.length ?? 0;
    lr += x.lines?.removed.length ?? 0;
  }
  const counts = { appeared: g.appeared.length, cleared: g.cleared.length, numbers: g.numbers.length, strings: g.strings.length, linesAdded: la, linesRemoved: lr, total: entries.length };
  const parts: string[] = [];
  if (g.appeared.length) parts.push(t('automations.page.diff.new', { n: g.appeared.length }));
  if (g.cleared.length) parts.push(t('automations.page.diff.cleared', { n: g.cleared.length }));
  if (g.numbers.length) parts.push(t(g.numbers.length === 1 ? 'automations.page.diff.number_one' : 'automations.page.diff.numbers', { n: g.numbers.length }));
  if (g.strings.length) parts.push(t(g.strings.length === 1 ? 'automations.page.diff.value_one' : 'automations.page.diff.values', { n: g.strings.length }));
  if (g.texts.length) parts.push(t('automations.page.diff.lines', { added: t(la === 1 ? 'automations.page.diff.line_added_one' : 'automations.page.diff.lines_added', { n: la }), removed: lr }));
  const same = !noReport && !entries.length;
  const lead = flip ? `${flip}, ` : '';
  const sentence = noReport
    ? (flip ?? t('automations.page.diff.no_report'))
    : parts.length
      ? lead + parts.join(', ')
      : lead + t('automations.page.diff.same_as', { n: b.number });
  return {
    base: b,
    head: h,
    entries,
    groups: g,
    deltas,
    flip,
    ignored: st.ignored,
    noReport,
    counts,
    sentence,
    same,
    hunks: [...g.appeared, ...g.cleared, ...g.numbers, ...g.strings, ...g.texts],
  };
}

export function previousIndex(runs: { run_id: string; status: string; has_report: boolean }[], index: number, lookup: (id: string) => ReportSlot): number {
  for (let j = index + 1; j < runs.length; j++) {
    const r = runs[j]!;
    if (r.status === 'succeeded' && r.has_report && usableReport(lookup(r.run_id)) !== undefined) return j;
  }
  return -1;
}

export function outputChanged(base: ReportSlot, head: ReportSlot): boolean | null {
  const a = usableReport(base);
  const b = usableReport(head);
  if (a === undefined || b === undefined) return null;
  return stable(a) !== stable(b);
}
