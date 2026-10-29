/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { SvelteMap } from 'svelte/reactivity';
import RunSheet from './RunSheet.svelte';
import { clockFor } from '../logic/words';
import type { ReportSlot } from '../logic/types';

const NOW = 1760000000;

function runOf(over: Record<string, unknown> = {}) {
  return {
    run_id: 'run-1', automation_id: 'a1', number: 3, status: 'succeeded', reason: null, error: null, trigger: 'schedule', attempt: 1,
    slot_at: NOW - 100, started_at: NOW - 90, ended_at: NOW - 80, skip_count: null, has_report: true, report_bytes: 120, cost_usd: null,
    host: 'studio', sessions: [], ...over,
  };
}
type Run = ReturnType<typeof runOf>;

interface Live { run: Run; slot: ReportSlot; onRetry: (() => void) | undefined; [k: string]: unknown }

let app: ReturnType<typeof mount> | null = null;

function show(run: Run, report: unknown, extra: Record<string, unknown> = {}, composition: 'pane' | 'reader' = 'reader'): Live {
  const m = new SvelteMap<string, unknown>(Object.entries({ run, slot: { state: 'ready', report }, composition, clock: clockFor('UTC'), tz: 'UTC', now: NOW, prev: null, onRetry: undefined, ...extra }));
  const props: Record<string, unknown> = {};
  for (const k of m.keys()) Object.defineProperty(props, k, { get: () => m.get(k), set: (v) => void m.set(k, v), enumerable: true });
  app = mount(RunSheet, { target: document.body, props: props as never });
  flushSync();
  return props as Live;
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const click = (el: Element | null) => { (el as HTMLElement).click(); flushSync(); };

test('a status array prints one tally line naming the failed row, and the rows fold is closed again after a redraw', () => {
  const checks = [{ name: 'api', status: 'ok' }, { name: 'worker', status: 'fail', detail: 'timeout' }];
  const props = show(runOf(), { checks });
  expect(document.querySelector('.r-rows-tally')!.textContent).toBe('1 ok, 1 fail');
  expect(document.querySelector('.r-rows-bad')!.textContent).toContain('worker');
  expect(document.querySelector('.r-rows-bad')!.textContent).toContain('timeout');
  const btn = document.querySelector('[data-r-toggle]')!;
  expect(btn.getAttribute('aria-expanded')).toBe('false');
  expect(btn.textContent).toBe('show 2 rows');
  expect(document.querySelector('table.r-table')).toBeNull();
  click(btn);
  expect(btn.getAttribute('aria-expanded')).toBe('true');
  expect(btn.textContent).toBe('hide 2 rows');
  expect(document.querySelector('table.r-table')).not.toBeNull();
  props.slot = { state: 'ready', report: { checks: checks.map((c) => ({ ...c })) } };
  flushSync();
  expect(document.querySelector('[data-r-toggle]')!.getAttribute('aria-expanded')).toBe('false');
  expect(document.querySelector('table.r-table')).toBeNull();
});

test('fix-it appears only on an object with both fix_prompt and finding_id, and asks for that finding', () => {
  const onFix = vi.fn();
  show(runOf({ status: 'failed' }), {
    items: [
      { label: 'has both', status: 'fail', fix_prompt: 'do it', finding_id: 'f1' },
      { label: 'prompt only', status: 'fail', fix_prompt: 'do it too' },
    ],
  }, { onFix });
  const buttons = document.querySelectorAll('[data-fix]');
  expect(buttons).toHaveLength(1);
  expect(buttons[0]!.closest('li')!.textContent).toContain('has both');
  click(buttons[0]!);
  expect(onFix).toHaveBeenCalledWith('run-1', 'f1');
});

test('stderr is above stdout on a failed run and below it on a succeeded one', () => {
  const report = { exit_code: 1, stdout_tail: 'out text', stderr_tail: 'err text' };
  show(runOf({ status: 'failed' }), report);
  expect([...document.querySelectorAll('[data-stream]')].map((e) => e.getAttribute('data-stream'))).toEqual(['stderr', 'stdout']);
  unmount(app!);
  document.body.innerHTML = '';
  show(runOf({ status: 'succeeded' }), report);
  expect([...document.querySelectorAll('[data-stream]')].map((e) => e.getAttribute('data-stream'))).toEqual(['stdout', 'stderr']);
});

test('a script tag inside markdown is drawn as text and never becomes an element', () => {
  show(runOf(), { summary: '# heading\n- item <script>window.__pwned = 1</script>\n**bold** and `<img src=x onerror=alert(1)>`' });
  expect(document.querySelector('script')).toBeNull();
  expect(document.querySelector('img')).toBeNull();
  expect(document.querySelector('.r-summary')!.textContent).toContain('<script>window.__pwned = 1</script>');
  expect((window as unknown as Record<string, unknown>).__pwned).toBeUndefined();
});

test('a stored pruned report shows the cleared state, a failed read shows try again, a pending report says loading', () => {
  const onRetry = vi.fn();
  const props = show(runOf(), { pruned: true });
  expect(document.body.textContent).toContain('report cleared to save space');
  expect(document.body.textContent).not.toContain('pruned');
  props.slot = { state: 'unreadable', reason: 'read_failed', message: 'the server said no' };
  props.onRetry = onRetry;
  flushSync();
  expect(document.body.textContent).toContain('could not read this report');
  expect(document.body.textContent).toContain('the server said no');
  click([...document.querySelectorAll('button')].find((b) => b.textContent === 'try again')!);
  expect(onRetry).toHaveBeenCalledTimes(1);
  props.slot = { state: 'pending' };
  flushSync();
  expect(document.body.textContent).toContain('loading report');
});

test('the pane composition has the header, the changes chip and the actions; a report at the cap carries the cap note', () => {
  show(runOf({ report_bytes: 524288, status: 'succeeded' }), { summary: 'all good' }, { onRunNow: vi.fn() }, 'pane');
  expect(document.querySelector('.r-head')!.textContent).toContain('of 1 MB cap');
  expect(document.querySelector('[data-chg]')!.textContent).toContain('first run with a report');
  expect(document.querySelector('[data-act="run"]')!.textContent).toBe('rerun');
  expect(document.body.textContent).toContain('of 1 MB cap: the whole report is not downloadable here');
});
