/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import TreeScheduledRow from './TreeScheduledRow.svelte';
import type { TaskManagerSchedule } from '../task-manager-schedules/task-manager-scheduled';

const trigger = (repeat: unknown) => ({ kind: 'at', fire_at: 1_900_000_000, fired_at: null, last_error: null, repeat });
const make = (over: Partial<TaskManagerSchedule> = {}): TaskManagerSchedule => ({
  list: '7', item: 11, title: 'weekly sweep', fireAt: 1_900_000_000, paused: false, state: 'pending', sessionKey: 'u-1', projectId: 7,
  repeat: { freq: 'daily', time: '09:00' },
  source: { id: 11, revision: 4, text: 'weekly sweep', title: 'weekly sweep', thread: [], start_trigger: trigger({ freq: 'daily', time: '09:00' }) } as never,
  ...over,
});

let app: ReturnType<typeof mount> | null = null;
const fetcher = vi.fn();
const onChanged = vi.fn();
const settle = async () => {
  for (let i = 0; i < 6; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

async function draw(schedule: TaskManagerSchedule): Promise<void> {
  const list = document.body.appendChild(document.createElement('ul'));
  app = mount(TreeScheduledRow, { target: list, props: { schedule, onChanged, fetcher: fetcher as never } });
  await settle();
}

beforeEach(() => {
  fetcher.mockReset();
  fetcher.mockResolvedValue({});
  onChanged.mockReset();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('the row says title, next time and repeat in words, with pause, edit and delete icons; a one-shot has no pause', async () => {
  await draw(make());
  expect(q('[data-tree-open-huddle]').textContent).toBe('weekly sweep');
  expect(q('[data-task-manager-schedule-when]').textContent).toMatch(/\d/);
  expect(q('[data-task-manager-schedule-when]').textContent).not.toContain('next');
  expect(q('[data-task-manager-schedule-repeat]').textContent).toContain('daily');
  expect(['pause', 'edit', 'delete'].every((k) => q(`[data-sched="${k}"] svg`) !== null)).toBe(true);
  unmount(app!);
  document.body.innerHTML = '';
  await draw(make({ repeat: null, source: { ...make().source!, start_trigger: trigger(null) } as never }));
  expect(document.querySelector('[data-sched="pause"]')).toBeNull();
  expect(q('[data-task-manager-schedule-repeat]').textContent).toBe('does not repeat');
});

test('pause PATCHes paused against the revision read, and a paused repeat resumes', async () => {
  await draw(make());
  q('[data-sched="pause"]').click();
  await settle();
  expect(fetcher).toHaveBeenCalledWith('/cplugs/huddle/items/11', { method: 'PATCH', body: JSON.stringify({ paused: true, expected_revision: 4 }) });
  expect(onChanged).toHaveBeenCalledTimes(1);
  unmount(app!);
  document.body.innerHTML = '';
  fetcher.mockClear();
  await draw(make({ paused: true, state: 'paused' }));
  expect(q('[data-task-manager-schedule-when]').textContent).toBe('paused');
  q('[data-sched="pause"]').click();
  await settle();
  expect(fetcher).toHaveBeenCalledWith('/cplugs/huddle/items/11', { method: 'PATCH', body: JSON.stringify({ paused: false, expected_revision: 4 }) });
});

test('delete asks first: nothing is sent until the confirm, and cancel sends nothing', async () => {
  await draw(make());
  q('[data-sched="delete"]').click();
  await settle();
  expect(q('[data-sched="warn"]').textContent).toContain('weekly sweep');
  expect(q('[data-sched="confirm"]').getAttribute('data-btn')).toBe('danger');
  expect(fetcher).not.toHaveBeenCalled();
  q('[data-sched="cancel"]').click();
  await settle();
  expect(document.querySelector('[data-sched="warn"]')).toBeNull();
  expect(fetcher).not.toHaveBeenCalled();
  q('[data-sched="delete"]').click();
  await settle();
  q('[data-sched="confirm"]').click();
  await settle();
  expect(fetcher).toHaveBeenCalledWith('/cplugs/huddle/items/11', { method: 'DELETE' });
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[data-sched="warn"]')).toBeNull();
});

test('edit opens the inline editor and save PATCHes the time and repeat; a refusal is said on the row', async () => {
  await draw(make());
  q('[data-sched="edit"]').click();
  await settle();
  const when = q<HTMLInputElement>('[data-sched="when"]');
  when.value = '2031-01-02T08:30';
  when.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  q('[data-sched="save"]').click();
  await settle();
  const [path, init] = fetcher.mock.calls[0]!;
  expect(path).toBe('/cplugs/huddle/items/11');
  expect(init.method).toBe('PATCH');
  expect(JSON.parse(init.body)).toMatchObject({ expected_revision: 4, repeat: { freq: 'daily', time: '08:30' } });
  expect(document.querySelector('[data-sched="editor"]')).toBeNull();
  fetcher.mockRejectedValueOnce(new Error('revision_conflict'));
  q('[data-sched="pause"]').click();
  await settle();
  expect(q('[data-sched="problem"]').textContent).toContain('revision_conflict');
});

test('a schedule read without its whole item is read only', async () => {
  await draw(make({ source: null }));
  expect(document.querySelector('[data-sched]')).toBeNull();
  expect(q('[data-tree-open-huddle]')).not.toBeNull();
});
