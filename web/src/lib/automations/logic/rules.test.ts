import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, test } from 'vitest';
import { COUNTER_IDS, counts, countAll } from './counters';
import { compare, isEmpty } from './diff';
import { analyse, changed, entries, foldText, isUnread, slotOf, type FeedRow } from './feed';
import { foldRuns } from './runs-fold';
import { face, likeKeys, metricTiles, rowsSummary, type RuleContext } from './report-rules';
import type { ReportLookup, ReportSlot } from './types';
import { clockFor, statusWord, tileLabel } from './words';

const NOW = 1760000000;
const clock = clockFor('UTC');
const ctx: RuleContext = { clock, tz: 'UTC', now: NOW };

function run(id: string, auto: string, status: string, ago: number, over: Partial<FeedRow> = {}): FeedRow {
  const at = NOW - ago;
  return {
    run_id: id,
    automation_id: auto,
    number: 1,
    trigger: 'schedule',
    attempt: 1,
    slot_at: at - 1,
    started_at: at - 2,
    ended_at: at,
    created_at: at - 3,
    status,
    reason: null,
    error: null,
    skip_count: null,
    has_report: status === 'succeeded' || status === 'failed',
    report_bytes: 100,
    cost_usd: null,
    ...over,
  };
}

const ready = (report: unknown): ReportSlot => ({ state: 'ready', report });
const lookupOf = (m: Record<string, ReportSlot>): ReportLookup => (id) => m[id] ?? { state: 'pending' };

describe('D7 tile labels', () => {
  test('a unit suffix leaves the label and shows on the value, and no label or value reads p95', () => {
    expect(tileLabel('slowest_check_ms')).toBe('slowest check');
    const tiles = metricTiles({ slowest_check_ms: 130, spend_usd: 30950.67, hit_rate_pct: 61.5, size_bytes: 22528, errors: 3, run_id: 7, exit_code: 0 }, null);
    expect(tiles.map((x) => [x.label, x.text])).toEqual([
      ['slowest check', '130 ms'],
      ['spend', '$30,950.67'],
      ['hit rate', '61.5%'],
      ['size', '22 KB'],
      ['errors', '3'],
    ]);
    expect(JSON.stringify(tiles).toLowerCase()).not.toContain('p95');
  });

  test('a tile carries its change against the previous report: new, same, or signed amount and percent', () => {
    const tiles = metricTiles({ errors: 3, hits: 10, fresh: 1 }, { errors: 2, hits: 10 });
    expect(tiles.map((x) => x.changeText)).toEqual(['+1 (+50%)', 'same', 'new']);
  });
});

describe('D8 rows', () => {
  const rows = [
    { name: 'db', status: 'ok' },
    { name: 'cache', status: 'OK' },
    { name: 'queue', status: 'ok' },
    { name: 'disk', status: 'ok' },
    { name: 'mail', status: 'ok' },
    { name: 'worker', status: 'fail', detail: 'timeout' },
  ];

  test('like-shaped rows are one count line: the tally in ok, warn, fail order and each not-ok row named', () => {
    expect(likeKeys(rows)).toBe(true);
    const s = rowsSummary([...rows, { name: 'api', status: 'warn', detail: 'slow' }]);
    expect(s.statusKey).toBe('status');
    expect(s.tally).toEqual([
      { word: 'ok', count: 5 },
      { word: 'warn', count: 1 },
      { word: 'fail', count: 1 },
    ]);
    expect(s.notOk.map((x) => [x.name, x.word, x.text])).toEqual([
      ['worker', 'fail', 'timeout'],
      ['api', 'warn', 'slow'],
    ]);
    expect(s.showLabel).toBe('show 7 rows');
  });

  test('more than eight not-ok rows list eight and count the rest; without a status column the line names the columns', () => {
    const many = Array.from({ length: 10 }, (_, i) => ({ name: `n${i}`, status: 'fail' }));
    const s = rowsSummary(many);
    expect(s.notOk).toHaveLength(8);
    expect(s.notOkMore).toBe(2);
    const plain = rowsSummary([{ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8 }]);
    expect(plain.statusKey).toBeNull();
    expect(plain.columns).toBe('a, b, c, d, e, f, +2');
    expect(plain.showLabel).toBe('show 1 row');
  });

  test('rows that do not share a shape are not like-shaped', () => {
    expect(likeKeys([{ a: 1 }, 5])).toBe(false);
    expect(likeKeys([{ a: 1 }, { b: 2 }, { c: 3 }])).toBe(false);
  });
});

describe('the face', () => {
  const r = run('r1', 'A', 'succeeded', 100);
  test('a report that has not arrived reads loading, a failed read and a pruned report say so, a summary wins otherwise', () => {
    expect(face(r, { state: 'pending' }, ctx)).toMatchObject({ text: 'loading report', rule: 'pending' });
    expect(face(r, { state: 'unreadable', reason: 'read_failed' }, ctx).text).toBe('could not read the report');
    expect(face(r, ready({ pruned: true }), ctx).text).toBe('report cleared to save space');
    expect(face(r, ready({ summary: '# 3 findings\nmore' }), ctx)).toMatchObject({ text: '3 findings', rule: 'summary' });
    expect(face(r, ready({ items: [{ status: 'ok' }, { status: 'fail' }, { status: 'ok' }] }), ctx).text).toBe('1 fail, 2 ok');
    expect(face(r, ready({ slowest_check_ms: 130 }), { ...ctx, prevReport: { slowest_check_ms: 125 } }).text).toBe('slowest check 130 ms (+4%)');
    expect(face(r, ready(null), ctx).text).toBe('ran and produced nothing');
  });
});

describe('the feed fold', () => {
  const X = { n: 1 };
  const Y = { n: 2 };
  const runs: FeedRow[] = [
    run('a1', 'A', 'succeeded', 100),
    run('a2', 'A', 'succeeded', 3700),
    run('a3', 'A', 'succeeded', 7300),
    run('a4', 'A', 'succeeded', 10900),
    run('b1', 'B', 'succeeded', 200),
    run('b2', 'B', 'succeeded', 3800),
    run('c1', 'C', 'succeeded', 300),
    run('c2', 'C', 'succeeded', 3900),
    run('d1', 'D', 'failed', 400, { error: 'boom' }),
    run('d2', 'D', 'failed', 4000, { error: 'boom' }),
    run('d3', 'D', 'failed', 4300, { error: 'boom' }),
    run('e1', 'E', 'skipped', 500, { reason: 'scheduler_paused', has_report: false }),
    run('e2', 'E', 'skipped', 4100, { reason: 'scheduler_paused', has_report: false }),
    run('e3', 'E', 'skipped', 4200, { reason: 'scheduler_paused', has_report: false }),
  ].sort((p, q) => (q.ended_at ?? 0) - (p.ended_at ?? 0));
  const lookup = lookupOf({
    a1: ready(X), a2: ready(X), a3: ready(X), a4: ready(Y),
    b2: ready(X),
    c1: ready({ pruned: true }), c2: ready({ pruned: true }),
    d1: ready({ exit_code: 1 }), d2: ready({ exit_code: 1 }), d3: ready({ exit_code: 1 }),
  });
  const info = analyse(runs, [], lookup);

  test('repeats of one automation fold under the newest, the changed run stays its own row, and the text reads from the fold', () => {
    const list = entries(runs.filter((x) => x.automation_id === 'A'), info, false, clock);
    expect(list.map((e) => [e.type, e.members.map((m) => m.run_id)])).toEqual([
      ['fold', ['a1', 'a2']],
      ['run', ['a3']],
      ['run', ['a4']],
    ]);
    expect(changed(info, runs.find((x) => x.run_id === 'a1')!)).toBe(false);
    expect(changed(info, runs.find((x) => x.run_id === 'a3')!)).toBe(true);
    const fold = list[0]!;
    expect(foldText(fold, 'n 1', clock)).toMatch(/^2 runs · same output \(n 1\) · \d\d:\d\d to \d\d:\d\d$/);
    expect(entries(runs.filter((x) => x.automation_id === 'A'), info, true, clock).every((e) => e.type === 'run')).toBe(true);
  });

  test('a pending report neither folds nor counts as changed', () => {
    const b1 = runs.find((x) => x.run_id === 'b1')!;
    expect(info.get('b1')).toMatchObject({ pending: true, same: false });
    expect(changed(info, b1)).toBe(false);
    expect(entries(runs.filter((x) => x.automation_id === 'B'), info, false, clock).map((e) => e.type)).toEqual(['run', 'run']);
  });

  test('a pruned report is unreadable and never folds; a failed run never folds; skips always fold', () => {
    expect(entries(runs.filter((x) => x.automation_id === 'C'), info, false, clock).map((e) => e.type)).toEqual(['run', 'run']);
    expect(slotOf(runs.find((x) => x.run_id === 'c1')!, lookup)).toMatchObject({ state: 'unreadable', reason: 'pruned' });
    expect(info.get('d1')).toMatchObject({ same: true });
    expect(entries(runs.filter((x) => x.automation_id === 'D'), info, false, clock).map((e) => e.type)).toEqual(['run', 'run', 'run']);
    expect(entries(runs.filter((x) => x.automation_id === 'E'), info, false, clock).map((e) => e.type)).toEqual(['fold', 'run']);
  });

  test('unread is after the seen-at line and not in the read set; an absent seen-at counts only the last 24 hours', () => {
    const fresh = run('u1', 'A', 'succeeded', 60);
    const old = run('u2', 'A', 'succeeded', 3 * 86400);
    expect(isUnread(fresh, { seenAt: null, read: new Set() }, NOW)).toBe(true);
    expect(isUnread(old, { seenAt: null, read: new Set() }, NOW)).toBe(false);
    expect(isUnread(fresh, { seenAt: null, read: new Set(['u1']) }, NOW)).toBe(false);
    expect(isUnread(old, { seenAt: new Date((NOW - 4 * 86400) * 1000).toISOString(), read: new Set() }, NOW)).toBe(true);
  });
});

describe('the pane runs-tab fold', () => {
  test('consecutive runs with the same status and reason fold while a success keeps the same output', () => {
    const list = [
      run('p1', 'A', 'succeeded', 100),
      run('p2', 'A', 'succeeded', 200),
      run('p3', 'A', 'succeeded', 300),
      run('p4', 'A', 'succeeded', 400),
      run('p5', 'A', 'failed', 500),
      run('p6', 'A', 'failed', 600),
    ];
    const lookup = lookupOf({ p1: ready({ n: 1 }), p2: ready({ n: 1 }), p3: ready({ n: 1 }), p4: ready({ n: 2 }), p5: ready({}), p6: ready({}) });
    expect(foldRuns(list, lookup).map((g) => g.runs.map((x) => x.run_id))).toEqual([['p1', 'p2', 'p3'], ['p4'], ['p5', 'p6']]);
  });
});

describe('the eight W4 counters', () => {
  const H = 3600;
  const base = { ended_at: null, started_at: null, slot_at: null, report_bytes: 50, output_empty: false } as const;
  const at = (ago: number) => ({ ended_at: NOW - ago });

  test('each predicate, with run time = ended_at, then started_at, then slot_at, then created_at', () => {
    const runs = [
      { ...base, status: 'succeeded', ...at(2 * H) },
      { ...base, status: 'succeeded', ...at(30 * H) },
      { ...base, status: 'succeeded', started_at: NOW - 10 * H },
      { ...base, status: 'succeeded', slot_at: NOW - 8 * 24 * H },
      { ...base, status: 'failed', ...at(23 * H) },
      { ...base, status: 'failed', ...at(25 * H) },
      { ...base, status: 'skipped', slot_at: NOW - 5 * 24 * H },
      { ...base, status: 'succeeded', ...at(H), report_bytes: 0 },
      { ...base, status: 'succeeded', ...at(H), output_empty: true },
      { ...base, status: 'failed', ...at(H), report_bytes: 0 },
      { ...base, status: 'running' },
      { ...base, status: 'claimed' },
      { ...base, status: 'waiting_on_you' },
    ];
    expect(countAll(runs, NOW)).toEqual({
      succeeded_24h: 4,
      failed_24h: 2,
      succeeded_7d: 5,
      failed_7d: 3,
      skipped_7d: 1,
      produced_nothing_7d: 2,
      running: 2,
      waiting_on_you: 1,
    });
    expect(COUNTER_IDS).toHaveLength(8);
    expect(counts('succeeded_7d', { ...base, status: 'succeeded', created_at: NOW - 9 * 24 * H }, NOW)).toBe(false);
    expect(counts('succeeded_7d', { ...base, status: 'succeeded', created_at: NOW - 6 * 24 * H }, NOW)).toBe(true);
  });
});

describe('the diff', () => {
  const side = (id: string, n: number, status: string, report: unknown, over: Partial<ReturnType<typeof dr>> = {}) => ({ run: { ...dr(id, n, status), ...over }, slot: ready(report) });
  function dr(id: string, n: number, status: string) {
    return { run_id: id, number: n, status, started_at: 10, ended_at: 12, report_bytes: 100, cost_usd: null as number | null };
  }
  const opts = { statusWord };

  test('volatile keys are ignored unless asked for, and the sentence counts what changed', () => {
    const a = { count: 10, status: 'ok', updated_at: 'then', rows: [{ id: 'x', v: 1 }], note: 'one\ntwo' };
    const b = { count: 12, status: 'fail', updated_at: 'now', rows: [{ id: 'x', v: 1 }, { id: 'y', v: 2 }], note: 'one\nthree\nfour' };
    const r = compare(side('r1', 1, 'succeeded', a), side('r2', 2, 'succeeded', b), opts);
    expect(r.ignored).toBe(1);
    expect(r.counts).toMatchObject({ appeared: 1, numbers: 1, strings: 1, linesAdded: 2, linesRemoved: 1 });
    expect(r.sentence).toBe('1 new, 1 number changed, 1 value changed, 2 lines added, 1 removed');
    const all = compare(side('r1', 1, 'succeeded', a), side('r2', 2, 'succeeded', b), { ...opts, showAll: true });
    expect(all.counts.strings).toBe(2);
    expect(all.ignored).toBe(0);
  });

  test('identical output reads "same as #n", a status flip leads the sentence, and an unreadable side compares nothing', () => {
    expect(compare(side('r1', 7, 'succeeded', { a: 1 }), side('r2', 8, 'succeeded', { a: 1 }), opts).sentence).toBe('same as #7');
    const flip = compare(side('r1', 1, 'failed', { a: 1 }), side('r2', 2, 'succeeded', { a: 2 }), opts);
    expect(flip.sentence).toBe('was failed, now succeeded, 1 number changed');
    const bad = compare({ run: dr('r1', 1, 'succeeded'), slot: { state: 'unreadable', reason: 'pruned' } }, side('r2', 2, 'succeeded', { a: 2 }), opts);
    expect(bad).toMatchObject({ noReport: true, sentence: 'no report to compare' });
  });
});

describe('isEmpty', () => {
  const cases = JSON.parse(readFileSync(fileURLToPath(new URL('../../../../../tests/fixtures/automations/report_empty_cases.json', import.meta.url)), 'utf8')) as {
    name: string;
    report: unknown;
    empty: boolean;
  }[];
  test('agrees with the server rule on every shared case', () => {
    expect(cases.length).toBeGreaterThan(10);
    for (const c of cases) expect(isEmpty(c.report), c.name).toBe(c.empty);
  });
});
