/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({ readLog: vi.fn(), putLogSettings: vi.fn() }));
vi.mock('./api', () => stub);
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import SchedulerLog from './SchedulerLog.svelte';
import { data } from './page-store.svelte';

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

beforeEach(async () => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.readLog.mockResolvedValue({ lines: [], settings: { rotate: 'size', max_mb: 10, keep: 5 } });
  app = mount(SchedulerLog, { target: document.body, props: { automationId: null } });
  await settle();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the scheduler log saves its rotation', async () => {
  stub.putLogSettings.mockResolvedValue({ rotate: 'daily', max_mb: 10, keep: 9 });
  const rotate = q<HTMLSelectElement>('[data-log-rotate]');
  rotate.value = 'daily';
  rotate.dispatchEvent(new Event('change', { bubbles: true }));
  const keep = q<HTMLInputElement>('[data-log-keep]');
  keep.value = '9';
  keep.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  q('[data-log-save]').click();
  await settle();
  expect(stub.putLogSettings).toHaveBeenCalledWith({ rotate: 'daily', max_mb: 10, keep: 9 });
});

test('the log dock names the automation and reads the reason in words, never an id or a code', async () => {
  unmount(app!);
  document.body.innerHTML = '';
  data.automations = [{ automation_id: 'aut_a', name: 'alpha' }] as never;
  stub.readLog.mockResolvedValue({
    lines: [
      { ts: 1_800_000_000, event: 'finished', status: 'failed', reason: 'exit_2', automation_id: 'aut_a' },
      { ts: 1_800_000_100, event: 'scheduled', automation_id: 'aut_gone' },
    ],
    settings: { rotate: 'size', max_mb: 10, keep: 5 },
  });
  app = mount(SchedulerLog, { target: document.body, props: { automationId: null } });
  await settle();
  const text = q('[data-log-lines]').textContent ?? '';
  expect(text).toContain('alpha');
  expect(text).toContain('deleted automation');
  expect(text).toContain('the command exited with code 2');
  expect(text).not.toContain('aut_');
  expect(text).not.toContain('exit_2');
});
