import { expect, test } from 'vitest';
import type { DiffEntry } from '../logic/diff';
import { attachmentRows, nextFires, runWords, sinceSentence, statusSentence } from './drawer-model';

const failedRun = { status: 'failed', reason: 'exit_2', title: 'the command failed' };

test('status sentence: off, paused, needs you (unreviewed) and the next run', () => {
  const base = { enabled: true, paused: false, last: null, reviewed: false, nextText: 'in 5 min, 9:05 am' };
  expect(statusSentence({ ...base, enabled: false })).toBe('off. it will not run until you turn it on.');
  expect(statusSentence({ ...base, paused: true })).toBe('the scheduler is paused, so scheduled runs are skipped.');
  expect(statusSentence({ ...base, last: failedRun })).toBe('the command failed.');
  expect(statusSentence({ ...base, last: failedRun, reviewed: true })).toBe('on. next run in 5 min, 9:05 am.');
  expect(statusSentence({ ...base, last: { status: 'succeeded', reason: null, title: 'finished' } })).toBe('on. next run in 5 min, 9:05 am.');
});

const entry = (e: Partial<DiffEntry>): DiffEntry => ({ kind: 'number', path: 'x', label: 'x', ...e }) as DiffEntry;
const counts = (total: number) => ({ appeared: 0, cleared: 0, numbers: 0, strings: 0, linesAdded: 0, linesRemoved: 0, total });

test('since sentence: same, went, moved, new, gone, count', () => {
  expect(sinceSentence(null)).toBe('');
  expect(sinceSentence({ same: true, entries: [], counts: counts(0) })).toBe('same as the run before.');
  expect(sinceSentence({ same: false, entries: [entry({ kind: 'string', label: 'status', old: 'ok', new: 'down' })], counts: counts(1) })).toBe('status went from ok to down.');
  expect(sinceSentence({ same: false, entries: [entry({ kind: 'number', label: 'a / b / count', old: 2, new: 5 })], counts: counts(1) })).toBe('b count moved from 2 to 5.');
  expect(sinceSentence({ same: false, entries: [entry({ kind: 'appeared', label: 'disk' })], counts: counts(1) })).toBe('disk is new.');
  expect(sinceSentence({ same: false, entries: [entry({ kind: 'cleared', label: 'disk' })], counts: counts(1) })).toBe('disk is gone.');
  expect(sinceSentence({ same: false, entries: [entry({ kind: 'text', label: 'log' })], counts: counts(1) })).toBe('1 thing changed since the run before.');
  expect(sinceSentence({ same: false, entries: [entry({ kind: 'text', label: 'log' })], counts: counts(3) })).toBe('3 things changed since the run before.');
});

test('next fires: the first three of the preview, else the row next fire, else none', () => {
  const fire = (s: number) => ({ utc: new Date(s * 1000).toISOString(), local: '' });
  const preview = { ok: true as const, fires: [1, 2, 3, 4, 5].map((n) => fire(1_800_000_000 + n * 60)) };
  expect(nextFires(preview, null)).toEqual([1, 2, 3].map((n) => 1_800_000_000 + n * 60));
  expect(nextFires({ ok: false, reason: 'floor' }, 1_800_000_999)).toEqual([1_800_000_999]);
  expect(nextFires(null, null)).toEqual([]);
});

test('a run with no title shows the feed face and no summary; attachments read name and size', () => {
  expect(runWords({ title: 'all 4 checks passed', summary: 'every check answered.' }, 'face')).toEqual({ title: 'all 4 checks passed', summary: 'every check answered.' });
  expect(runWords({ title: null, summary: null }, 'exit code 2')).toEqual({ title: 'exit code 2', summary: '' });
  expect(runWords({}, 'face')).toEqual({ title: 'face', summary: '' });
  expect(attachmentRows([{ name: 'a.png', bytes: 2048, mime: 'image/png' }])).toEqual([{ name: 'a.png', size: '2 KB' }]);
  expect(attachmentRows(null)).toEqual([]);
});
