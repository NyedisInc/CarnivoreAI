/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

globalThis.ResizeObserver ??= class { observe(): void {} unobserve(): void {} disconnect(): void {} } as unknown as typeof ResizeObserver;

import LogViewer from './LogViewer.svelte';
import { LOG_LEVELS, writeLevels } from './log-levels';
import type { LogPage, LogRecord, LogSource } from './types';

const rec = (id: number, event: string): LogRecord => ({
  id: `7-${id}`, timestamp: `2026-10-15T19:00:0${id}Z`, level: 'error', source: 'server', event, fields: {}, lines: [], dropped_lines: 0,
  traceback: false, continues: false, approx_time: false,
} as LogRecord);
const page = (records: LogRecord[], extra: Partial<LogPage> = {}): LogPage => ({ records, head: '7-9', before: 'cursor-a', gap: false, reset: false, ...extra });

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) {
    await Promise.resolve();
    await tick();
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  await new Promise((resolve) => setTimeout(resolve, 300));
  flushSync();
}

test('an older page that lands after a reset is dropped', async () => {
  writeLevels([...LOG_LEVELS]);
  let deliver: (got: LogPage) => void = () => undefined;
  let answer: (got: LogPage) => void = () => undefined;
  const source: LogSource = {
    backfill: () => new Promise<LogPage>((resolve) => (answer = resolve)),
    subscribe: (onBatch) => { deliver = onBatch; return () => undefined; },
    readLevel: async () => ({ level: 'info', source: 'env', env_level: 'info', choices: [], expires_at: null }) as never,
    setLevel: async () => ({}) as never,
  };
  const target = document.createElement('div');
  document.body.append(target);
  app = mount(LogViewer, { target, props: { source } });
  deliver(page([rec(2, 'newest')]));
  await settle();
  (target.querySelector('[data-log-older]') as HTMLButtonElement).click();
  flushSync();
  deliver(page([rec(5, 'fresh')], { reset: true, before: 'cursor-b' }));
  await settle();
  answer(page([rec(1, 'stale')], { before: 'cursor-stale' }));
  await settle();
  const events = [...target.querySelectorAll('[data-log-row] .oc-lv-event')].map((n) => n.textContent);
  expect(events).toEqual(['fresh']);
});
