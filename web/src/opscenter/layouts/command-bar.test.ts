import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { CommandBar, type BarDeps } from './command-bar.svelte';
import { LayoutSearch, type DrivenSearch, type SearchTarget } from './layout-search.svelte';
import { TYPE_DEBOUNCE_MS } from '../../lib/terminal-search/search-controller.svelte';
import type { BroadcastAnswer } from './api';

function cell(count: number | null): DrivenSearch & { calls: string[] } {
  const calls: string[] = [];
  return {
    calls,
    query: '',
    get matchCount() { return this.query ? count : null; },
    drive() { calls.push('drive'); },
    release() { calls.push('release'); },
    runQuery() { calls.push(`run:${this.query}`); },
    step(dir) { calls.push(`step:${dir}`); },
  };
}

const ANSWER: BroadcastAnswer = {
  layout_uuid: 'L1', sent: 2, skipped: 1, failed: 1,
  results: [
    { session_row_id: 1, session_uuid: 'u1', status: 'sent', code: null },
    { session_row_id: 2, session_uuid: 'u2', status: 'skipped_off', code: null },
    { session_row_id: 3, session_uuid: 'u3', status: 'failed', code: 'pane_dialog_open' },
    { session_row_id: 4, session_uuid: 'u4', status: 'sent', code: null },
  ],
};

function deps(over: Partial<BarDeps> = {}): BarDeps & { sent: string[]; searched: string[] } {
  const sent: string[] = [];
  const searched: string[] = [];
  return {
    sent,
    searched,
    search: { run: (q) => searched.push(`run:${q}`), release: () => searched.push('release'),
      step: (d) => searched.push(`step:${d}`) },
    send: async (text) => { sent.push(text); return ANSWER; },
    recipients: () => ({ receiving: 3, total: 4, busy: [] }),
    confirmBusy: async () => true,
    nameOf: (row) => `s${row}`,
    reason: (e) => String(e),
    ...over,
  };
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); });

test('search is the default and typing runs one debounced query', () => {
  const d = deps();
  const bar = new CommandBar(d);
  expect(bar.mode).toBe('search');
  bar.input('e'); bar.input('er'); bar.input('err');
  expect(d.searched).toEqual([]);
  vi.advanceTimersByTime(TYPE_DEBOUNCE_MS);
  expect(d.searched).toEqual(['run:err']);
});

test('enter and shift+enter walk matches; a pending query runs first', () => {
  const d = deps();
  const bar = new CommandBar(d);
  bar.input('x');
  expect(bar.key('Enter')).toBe('handled');
  expect(bar.key('Enter', true)).toBe('handled');
  expect(d.searched).toEqual(['run:x', 'step:next', 'step:prev']);
  expect(d.sent).toEqual([]);
});

test('escape clears a full box, then asks to blur an empty one', () => {
  const d = deps();
  const bar = new CommandBar(d);
  bar.input('x');
  expect(bar.key('Escape')).toBe('handled');
  expect(bar.text).toBe('');
  expect(d.searched).toContain('release');
  expect(bar.key('Escape')).toBe('blur');
  expect(bar.key('a')).toBe('ignored');
});

test('the two mode icons select their own mode; a switch empties the box', () => {
  const d = deps();
  const bar = new CommandBar(d);
  bar.input('x');
  bar.setMode('command');
  expect(bar.mode).toBe('command');
  expect(bar.text).toBe('');
  expect(d.searched).toContain('release');
  bar.setMode('search');
  expect(bar.mode).toBe('search');
  bar.setMode('command');
  bar.setMode('command');
  expect(bar.mode).toBe('command');
  vi.advanceTimersByTime(TYPE_DEBOUNCE_MS);
  expect(d.searched.filter((one) => one.startsWith('run:'))).toEqual([]);
});

test('enter in command mode sends the line once and says what was skipped or failed', async () => {
  const d = deps();
  const bar = new CommandBar(d);
  bar.setMode('command');
  bar.input('git status');
  bar.key('Enter');
  bar.key('Enter');
  await vi.runAllTimersAsync();
  expect(d.sent).toEqual(['git status']);
  expect(bar.text).toBe('');
  expect(bar.line).toContain('s3 (pane_dialog_open)');
});

test('a clean send (nothing skipped, nothing failed) says nothing: enter is already the confirmation', async () => {
  const clean: BroadcastAnswer = { layout_uuid: 'L1', sent: 3, skipped: 0, failed: 0, results: [
    { session_row_id: 1, session_uuid: 'u1', status: 'sent', code: null },
  ] };
  const d = deps({ send: async (text) => { d.sent.push(text); return clean; } });
  const bar = new CommandBar(d);
  bar.setMode('command');
  bar.input('git status');
  await bar.send();
  expect(d.sent).toEqual(['git status']);
  expect(bar.line).toBe('');
});

test('nobody receiving sends nothing and says so', async () => {
  const d = deps({ recipients: () => ({ receiving: 0, total: 3, busy: [] }) });
  const bar = new CommandBar(d);
  bar.setMode('command');
  bar.input('ls');
  await bar.send();
  expect(d.sent).toEqual([]);
  expect(bar.text).toBe('ls');
  expect(bar.line).not.toBe('');
});

test('a working recipient asks first, and a cancel sends nothing', async () => {
  const asked: string[][] = [];
  let answer = false;
  const d = deps({
    recipients: () => ({ receiving: 2, total: 2, busy: ['api'] }),
    confirmBusy: async (names) => { asked.push(names); return answer; },
  });
  const bar = new CommandBar(d);
  bar.setMode('command');
  bar.input('ls');
  await bar.send();
  expect(asked).toEqual([['api']]);
  expect(d.sent).toEqual([]);
  answer = true;
  await bar.send();
  expect(d.sent).toEqual(['ls']);
});

test('no question when nobody is mid-task', async () => {
  let asked = 0;
  const d = deps({ confirmBusy: async () => { asked += 1; return true; } });
  const bar = new CommandBar(d);
  bar.setMode('command');
  bar.input('ls');
  await bar.send();
  expect(asked).toBe(0);
  expect(d.sent).toEqual(['ls']);
});

test('a refused send keeps the line and shows the reason', async () => {
  const d = deps({ send: async () => { throw new Error('the text holds a control character'); } });
  const bar = new CommandBar(d);
  bar.setMode('command');
  bar.input('ls');
  await bar.send();
  expect(bar.text).toBe('ls');
  expect(bar.line).toContain('control character');
  expect(bar.sending).toBe(false);
});


function layoutSearchOver(counts: (number | null)[]) {
  const cells = counts.map((n) => cell(n));
  const targets: SearchTarget[] = cells.map((controller, i) => ({ rowId: i + 1, controller }));
  return { cells, search: new LayoutSearch(() => targets) };
}

test('a query drives every cell and totals their counts', () => {
  const { cells, search } = layoutSearchOver([2, 0, 3, null]);
  search.run('err');
  for (const one of cells) expect(one.calls).toEqual(['drive', 'run:err']);
  expect(search.countFor(1)).toBe(2);
  expect(search.countFor(4)).toBeNull();
  expect(search.total).toBe(5);
  search.run('');
  for (const one of cells) expect(one.calls.at(-1)).toBe('release');
  expect(search.total).toBeNull();
});

test('next steps inside a cell, then lands on the next cell with matches, and wraps', () => {
  const { cells, search } = layoutSearchOver([2, 0, 1]);
  search.run('x');
  cells.forEach((one) => one.calls.splice(0));
  search.step('next');
  expect([search.current, search.position]).toEqual([1, 1]);
  search.step('next');
  expect(cells[0]!.calls).toEqual(['run:x', 'step:next']);
  expect([search.current, search.position]).toEqual([1, 2]);
  search.step('next');
  expect(cells[1]!.calls).toEqual([]);
  expect([search.current, search.position]).toEqual([3, 3]);
  search.step('next');
  expect([search.current, search.position]).toEqual([1, 1]);
});

test('previous from a cell\'s first match lands on the previous cell\'s last', () => {
  const { cells, search } = layoutSearchOver([3, 1]);
  search.run('x');
  search.step('next');
  search.step('prev');
  expect(search.current).toBe(2);
  expect(search.position).toBe(4);
  cells[0]!.calls.splice(0);
  search.step('prev');
  expect(search.current).toBe(1);
  expect(cells[0]!.calls).toEqual(['run:x', 'step:prev']);
  expect(search.position).toBe(3);
});
