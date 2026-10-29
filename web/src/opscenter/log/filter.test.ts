import { describe, expect, test } from 'vitest';
import { compile, compileText, emptyFilter, sessionOf, sourcesOf, toggleField, SESSION_KEYS } from './filter';
import { RecordBuffer } from './buffer';
import { toJsonl, recordLine } from './export';
import { layout, windowAt } from './virtual';
import type { LogRecord } from './types';

let next = 0;

function rec(over: Partial<LogRecord> = {}): LogRecord {
  next += 1;
  return {
    id: `1-${next}`, timestamp: '2026-10-16T10:00:00Z', level: 'info', source: 'server', event: `e${next}`, fields: {},
    lines: [], dropped_lines: 0, traceback: false, continues: false, approx_time: false, ...over,
  };
}

describe('filter', () => {
  test('levels, sources and the empty flag', () => {
    const records = [rec({ level: 'error' }), rec({ level: 'debug', source: 'uvicorn.access' })];
    expect(compile(emptyFilter()).empty).toBe(true);
    const errorsOnly = compile({ ...emptyFilter(), levels: ['error'] });
    expect(records.filter(errorsOnly.match)).toEqual([records[0]]);
    const noAccess = compile({ ...emptyFilter(), hiddenSources: ['uvicorn.access'] });
    expect(records.filter(noAccess.match)).toEqual([records[0]]);
  });

  test('session matches any of the session keys', () => {
    const records = SESSION_KEYS.map((key) => rec({ fields: { [key]: `carnivore_${key}` } }));
    const all = compile({ ...emptyFilter(), session: 'CARNIVORE_' });
    expect(records.filter(all.match)).toHaveLength(SESSION_KEYS.length);
    expect(records.filter(compile({ ...emptyFilter(), session: 'tmux_name' }).match)).toHaveLength(1);
    expect(sessionOf(rec({ fields: { other: 'x' } }))).toBeNull();
  });

  test('free text searches event, fields and continuation lines; /regex/ is a pattern', () => {
    const a = rec({ event: 'boot', fields: { port: '8000' } });
    const b = rec({ event: 'crash', lines: ['ValueError: Boom'] });
    expect([a, b].filter(compile({ ...emptyFilter(), text: 'port=8000' }).match)).toEqual([a]);
    expect([a, b].filter(compile({ ...emptyFilter(), text: 'boom' }).match)).toEqual([b]);
    expect([a, b].filter(compile({ ...emptyFilter(), text: '/^(boot|crash)$/m' }).match)).toEqual([a, b]);
    expect([a, b].filter(compile({ ...emptyFilter(), text: '/Boom$/' }).match)).toEqual([b]);
    const broken = compileText('/(/');
    expect(broken.error).toBeTruthy();
    expect(broken.test('anything')).toBe(false);
  });

  test('field chips: click filters in, alt-click out, the same click again removes', () => {
    const a = rec({ fields: { route: '/a' } });
    const b = rec({ fields: { route: '/b' } });
    let f = toggleField(emptyFilter(), 'route', '/a', false);
    expect([a, b].filter(compile(f).match)).toEqual([a]);
    f = toggleField(f, 'route', '/a', true);
    expect(f.fields).toEqual([{ key: 'route', value: '/a', exclude: true }]);
    expect([a, b].filter(compile(f).match)).toEqual([b]);
    f = toggleField(f, 'route', '/a', true);
    expect(f.fields).toEqual([]);
  });

  test('sources are listed most common first', () => {
    expect(sourcesOf([rec({ source: 'stderr' }), rec(), rec()])).toEqual(['server', 'stderr']);
  });
});

describe('continuation grouping in the buffer', () => {
  test('a leading orphan of a new batch joins the last held record', () => {
    const buffer = new RecordBuffer();
    const event = rec({ event: 'request failed', lines: ['Traceback (most recent call last):'] });
    buffer.append([event]);
    const orphan = rec({ level: 'error', source: 'stderr', event: '  File "x.py", line 3', lines: ['KeyError: 1'], continues: true, traceback: true });
    expect(buffer.append([orphan, rec({ event: 'next' })])).toBe(1);
    expect(buffer.records.map((r) => r.event)).toEqual(['request failed', 'next']);
    expect(buffer.records[0]?.lines).toEqual(['Traceback (most recent call last):', '  File "x.py", line 3', 'KeyError: 1']);
    expect(buffer.records[0]?.traceback).toBe(true);
  });

  test('an orphan with nothing before it stays its own error record', () => {
    const buffer = new RecordBuffer();
    buffer.append([rec({ level: 'error', event: 'stray', continues: true })]);
    expect(buffer.records.map((r) => r.event)).toEqual(['stray']);
  });

  test('an older page takes the held leading orphan onto its last record', () => {
    const buffer = new RecordBuffer();
    buffer.append([rec({ event: 'tail line', continues: true }), rec({ event: 'later' })]);
    expect(buffer.prepend([rec({ event: 'first' }), rec({ event: 'owner' })])).toBe(2);
    expect(buffer.records.map((r) => r.event)).toEqual(['first', 'owner', 'later']);
    expect(buffer.records[1]?.lines).toEqual(['tail line']);
  });
});

describe('the ring buffer bounds', () => {
  test('the oldest records drop from the front and are counted', () => {
    const buffer = new RecordBuffer(3, 1_000_000);
    buffer.append([rec({ event: 'a' }), rec({ event: 'b' }), rec({ event: 'c' }), rec({ event: 'd' }), rec({ event: 'e' })]);
    expect(buffer.records.map((r) => r.event)).toEqual(['c', 'd', 'e']);
    expect(buffer.dropped).toBe(2);
  });

  test('the byte bound holds too, and a full buffer refuses older pages instead of dropping live ones', () => {
    const buffer = new RecordBuffer(100, 400);
    buffer.append([rec({ event: 'x'.repeat(150) }), rec({ event: 'y'.repeat(150) }), rec({ event: 'z'.repeat(150) })]);
    expect(buffer.records.map((r) => r.event[0])).toEqual(['z']);
    expect(buffer.bytes).toBeLessThanOrEqual(400);
    expect(buffer.prepend([rec({ event: 'o'.repeat(300) })])).toBe(0);
    expect(buffer.refused).toBe(1);
    expect(buffer.records.map((r) => r.event[0])).toEqual(['z']);
  });
});

describe('export and the virtual window', () => {
  test('jsonl is one record per line; a copied line carries fields and continuation', () => {
    const a = rec({ event: 'boot', fields: { port: '8000' }, lines: ['more'] });
    expect(toJsonl([a, a]).split('\n')).toHaveLength(3);
    expect(JSON.parse(toJsonl([a]).trim()).event).toBe('boot');
    expect(recordLine(a)).toBe('2026-10-16T10:00:00Z info server boot port=8000\nmore');
    expect(toJsonl([])).toBe('');
  });

  test('the window covers the viewport plus overscan, and an expanded row moves the rest', () => {
    const ids = Array.from({ length: 1000 }, (_, i) => `r${i}`);
    const flat = layout(ids, 20, new Map());
    expect(flat.offsets[1000]).toBe(20000);
    const win = windowAt(flat, 2000, 200);
    expect(win.start).toBeLessThanOrEqual(100);
    expect(win.end).toBeGreaterThanOrEqual(110);
    expect(win.end - win.start).toBeLessThan(40);
    const tall = layout(ids, 20, new Map([['r0', 220]]));
    expect(tall.offsets[1]).toBe(220);
    expect(windowAt(tall, 220, 20).start).toBeLessThanOrEqual(1);
  });
});
