/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TaskManagerProgress from './TaskManagerProgress.svelte';
import { applyProgress, taskManagerProgress, parse } from './task-manager-progress.svelte';
import { clip, elapsed, isStale } from './huddle-progress';

const line = (over: Record<string, unknown> = {}) => ({ worker: 'main', phase: 'running', note: 'building the strip', age_s: 5, stale: false, ...over });

let host: HTMLElement | null = null;
let handle: ReturnType<typeof mount> | null = null;

function show(full = false): HTMLElement {
  host = document.createElement('div');
  document.body.append(host);
  handle = mount(TaskManagerProgress, { target: host, props: { id: 7, full } });
  flushSync();
  return host;
}

afterEach(() => {
  if (handle) unmount(handle);
  host?.remove();
  handle = host = null;
  applyProgress({ progress: {} });
  vi.useRealTimers();
});

describe('the pure parts', () => {
  test('clip cuts at 60 with an ellipsis, elapsed reads short', () => {
    expect(clip('a'.repeat(70))).toHaveLength(60);
    expect(clip('a'.repeat(70)).endsWith('…')).toBe(true);
    expect(clip('short')).toBe('short');
    expect([elapsed(5), elapsed(125), elapsed(3900), elapsed(7200)]).toEqual(['5s', '2m', '1h 5m', '2h']);
    expect([elapsed(86_399), elapsed(86_400), elapsed(193 * 3600 + 240)]).toEqual(['23h 59m', '1d', '8d']);
  });

  test('a line is stale when the server says so or the view has waited past 30 minutes', () => {
    expect(isStale(line() as never, 0)).toBe(false);
    expect(isStale(line({ stale: true }) as never, 0)).toBe(true);
    expect(isStale(line({ age_s: 1790 }) as never, 11_000)).toBe(true);
  });

  test('parse drops malformed lines and empty items', () => {
    expect(parse({ progress: { '7': [line(), { nope: 1 }], '8': [{ nope: 1 }] } })).toEqual({ '7': [line()] });
    expect(parse(null)).toEqual({});
  });
});

describe('the strip', () => {
  test('hides when nothing is live', () => {
    expect(show().querySelector('[data-task-manager-progress]')).toBeNull();
  });

  test('one line per worker, a phase chip each, the note and the elapsed time', () => {
    applyProgress({ progress: { '7': [line({ worker: 'web', phase: 'testing', note: '12 of 40', age_s: 125 }), line({ worker: 'api', phase: 'blocked' })] } });
    const root = show();
    const rows = [...root.querySelectorAll<HTMLElement>('[data-task-manager-progress-worker]')];
    expect(rows.map((r) => [r.dataset.taskManagerProgressWorker, r.dataset.phase])).toEqual([['web', 'testing'], ['api', 'blocked']]);
    expect(rows[0].querySelector('.hdp-chip')).not.toBeNull();
    expect(rows[0].querySelector('.hdp-note')?.textContent).toBe('12 of 40');
    expect(rows[0].querySelector('.hdp-age')?.textContent).toBe('2m');
    expect(root.querySelector('[data-task-manager-progress="8"]')).toBeNull();
  });

  test('the row clips a long note; the open view shows it whole', () => {
    const long = 'x'.repeat(100);
    applyProgress({ progress: { '7': [line({ note: long })] } });
    expect(show().querySelector('.hdp-note')?.textContent).toHaveLength(60);
    unmount(handle!); host!.remove();
    expect(show(true).querySelector('.hdp-note')?.textContent).toBe(long);
  });

  test('a stale line is marked and dimmed, and a push that empties the item hides the strip', () => {
    applyProgress({ progress: { '7': [line({ stale: true, age_s: 2000 })] } });
    const root = show();
    expect(root.querySelector<HTMLElement>('[data-task-manager-progress-worker]')?.dataset.stale).toBe('true');
    applyProgress({ progress: {} });
    flushSync();
    expect(root.querySelector('[data-task-manager-progress]')).toBeNull();
    expect(taskManagerProgress.byItem).toEqual({});
  });
});
