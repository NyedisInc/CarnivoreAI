/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { menuNode, openRowMenu } from './row-menu-driver.test.helper';

const server = vi.hoisted(() => ({ items: [] as unknown[], patches: [] as { path: string; body: Record<string, unknown> }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (init.method === 'PATCH') server.patches.push({ path, body: JSON.parse(String(init.body)) as Record<string, unknown> });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: 'all', name: null, project_id: null, items: 3, open: 3, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0, incomplete: 3 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: 'all', revision: 9, cursor: 9, groups: [], items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { clockLabel, defaultLocalInput, defaultRepeat, draftOf, dueLabel, dueState, fromLocalInput, repeatLabel, ruleFromDraft, toLocalInput } from './task-manager-schedule';
import type { HuddleItem } from './huddle-model';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

const WORDS = { today: 'today', tomorrow: 'tomorrow' };
const NOW = new Date(2026, 9, 5, 10, 0, 0);
const at = (y: number, mo: number, d: number, h: number, mi = 0): number => new Date(y, mo - 1, d, h, mi).getTime() / 1000;
const trigger = (fire_at: number, extra: Record<string, unknown> = {}) => ({ kind: 'at', fire_at, fired_at: null, last_error: null, ...extra });

const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: id, revision: 3, created_seq: id,
  seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', start_trigger: null, ...extra,
});

describe('the label and the picker value', () => {
  test('today, tomorrow, a weekday within the week, else a date; lowercase', () => {
    expect(dueLabel(at(2026, 10, 5, 15), NOW, WORDS, 'en-US')).toBe('today 3:00 pm');
    expect(dueLabel(at(2026, 10, 6, 9), NOW, WORDS, 'en-US')).toBe('tomorrow 9:00 am');
    expect(dueLabel(at(2026, 10, 8, 9, 30), NOW, WORDS, 'en-US')).toBe('thu 9:30 am');
    expect(dueLabel(at(2026, 10, 20, 17), NOW, WORDS, 'en-US')).toBe('oct 20 5:00 pm');
    expect(dueLabel(at(2026, 10, 4, 8), NOW, WORDS, 'en-US')).toBe('oct 4 8:00 am');
  });

  test('the picker value round-trips through an ISO time that carries the offset', () => {
    const stamp = at(2026, 10, 6, 15);
    expect(toLocalInput(stamp)).toBe('2026-10-06T15:00');
    const iso = fromLocalInput('2026-10-06T15:00')!;
    expect(new Date(iso).getTime() / 1000).toBe(stamp);
    expect(iso).toMatch(/Z$|[+-]\d\d:\d\d$/);
    expect(fromLocalInput('')).toBeNull();
    expect(fromLocalInput('not a time')).toBeNull();
    expect(defaultLocalInput(NOW)).toBe('2026-10-05T11:00');
  });

  test('the state: none, pending, fired, failed (a failure wins)', () => {
    expect(dueState(mk(1) as unknown as HuddleItem)).toBeNull();
    expect(dueState(mk(1, { start_trigger: trigger(1) }) as unknown as HuddleItem)).toBe('pending');
    expect(dueState(mk(1, { start_trigger: trigger(1, { fired_at: 2 }) }) as unknown as HuddleItem)).toBe('fired');
    expect(dueState(mk(1, { start_trigger: trigger(1, { fired_at: 2, last_error: 'no session' }) }) as unknown as HuddleItem)).toBe('failed');
  });
});

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(): Promise<HTMLElement> {
  await refreshPrefs();
  await refreshTaskManager();
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

beforeEach(() => {
  server.patches = [];
  huddle.selected = 'all';
  huddle.openId = null;
  const soon = Date.now() / 1000 + 3 * 3600;
  server.items = [
    mk(1, { start_trigger: trigger(soon) }),
    mk(2, { start_trigger: trigger(soon, { fired_at: soon, last_error: 'could not start a session' }) }),
    mk(3),
  ];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the repeat rule on the client', () => {
  const tr = (key: string, params: Record<string, string | number> = {}): string => ({
    'cplug.huddle.schedule.repeat_daily': `daily ${params.time}`, 'cplug.huddle.schedule.repeat_weekdays': `weekdays ${params.time}`,
    'cplug.huddle.schedule.repeat_hour': 'every hour', 'cplug.huddle.schedule.repeat_hours': `every ${params.n} hours`,
    'cplug.huddle.schedule.repeat_monthly': `monthly on day ${params.day} ${params.time}`,
  } as Record<string, string>)[key] ?? key;

  test('labels: daily, weekdays, picked days, hours, monthly', () => {
    expect(clockLabel('09:00', 'en-US')).toBe('9:00 am');
    expect(repeatLabel({ freq: 'daily', time: '15:30' }, tr, 'en-US')).toBe('daily 3:30 pm');
    expect(repeatLabel({ freq: 'weekly', byweekday: [0, 1, 2, 3, 4], time: '09:00' }, tr, 'en-US')).toBe('weekdays 9:00 am');
    expect(repeatLabel({ freq: 'weekly', byweekday: [0, 2], time: '09:00' }, tr, 'en-US')).toBe('mon, wed 9:00 am');
    expect(repeatLabel({ freq: 'hourly', interval: 4 }, tr)).toBe('every 4 hours');
    expect(repeatLabel({ freq: 'hourly', interval: 1 }, tr)).toBe('every hour');
    expect(repeatLabel({ freq: 'monthly', monthday: 31, time: '09:00' }, tr, 'en-US')).toBe('monthly on day 31 9:00 am');
  });

  test('the picker draft becomes the server rule and back', () => {
    const base = defaultRepeat();
    expect(ruleFromDraft(base, '2026-10-06T09:00')).toBeNull();
    expect(ruleFromDraft({ ...base, kind: 'daily' }, '2026-10-06T09:05')).toEqual({ freq: 'daily', time: '09:05' });
    expect(ruleFromDraft({ ...base, kind: 'weekly', days: [4, 0] }, '2026-10-06T09:00')).toEqual({ freq: 'weekly', byweekday: [0, 4], time: '09:00' });
    expect(ruleFromDraft({ ...base, kind: 'weekly', days: [] }, '2026-10-06T09:00')).toBeNull();
    expect(ruleFromDraft({ ...base, kind: 'hours', hours: 999 }, '')).toEqual({ freq: 'hourly', interval: 168 });
    expect(ruleFromDraft({ ...base, kind: 'monthly', monthday: 31 }, '2026-10-06T09:00')).toEqual({ freq: 'monthly', monthday: 31, time: '09:00' });
    expect(draftOf({ freq: 'hourly', interval: 6 })).toMatchObject({ kind: 'hours', hours: 6 });
    expect(draftOf({ freq: 'monthly', monthday: 15, time: '08:00' })).toMatchObject({ kind: 'monthly', monthday: 15 });
    expect(draftOf(null).kind).toBe('none');
  });

  test('a repeating trigger is pending or paused, never sent', () => {
    const rule = { freq: 'daily', time: '09:00' };
    expect(dueState(mk(1, { start_trigger: trigger(1, { repeat: rule }) }) as unknown as HuddleItem)).toBe('pending');
    expect(dueState(mk(1, { start_trigger: trigger(1, { repeat: rule, paused: true }) }) as unknown as HuddleItem)).toBe('paused');
    expect(dueState(mk(1, { start_trigger: trigger(1, { repeat: rule, last_error: 'x' }) }) as unknown as HuddleItem)).toBe('failed');
  });
});

describe('the row', () => {
  test('a scheduled row wears a clock and its time; a failed one says so; an unscheduled one wears nothing', async () => {
    const host = await mountBody();
    const pending = host.querySelector<HTMLElement>('[data-task-manager-due="1"]')!;
    expect(pending.dataset.dueState).toBe('pending');
    expect(pending.querySelector('svg')).not.toBeNull();
    expect(pending.textContent).toMatch(/(today|tomorrow) \d{1,2}:\d\d (am|pm)/);
    expect(host.querySelector<HTMLElement>('[data-task-manager-due="2"]')!.dataset.dueState).toBe('failed');
    expect(host.querySelector('[data-task-manager-due="3"]')).toBeNull();
  });

  test('the open item sets a time (a PATCH with an offset), changes it, and cancels it with an empty fire_at', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="3"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-schedule="3"]')).toBeNull();
    openRowMenu(host, 3);
    await settle();
    menuNode('schedule')!.click();
    await settle();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-schedule-input="3"]')!;
    input.value = '2026-12-24T09:15';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-schedule-save="3"]')!.click();
    await settle();
    const set = server.patches.at(-1)!;
    expect(set.path).toBe('/cplugs/huddle/items/3');
    expect(new Date(String(set.body.fire_at)).getTime()).toBe(new Date(2026, 11, 24, 9, 15).getTime());
    expect(set.body.expected_revision).toBe(3);

    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-schedule-cancel="1"]')!.click();
    await settle();
    expect(server.patches.at(-1)!.body).toEqual({ fire_at: '', expected_revision: 3 });
  });

  test('the repeat picker: every n hours sends the time and the rule; weekdays send the rule alone with the picked time', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="3"]')!.click();
    await settle();
    openRowMenu(host, 3);
    await settle();
    menuNode('schedule')!.click();
    await settle();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-schedule-input="3"]')!;
    input.value = '2026-12-24T09:15';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    const kind = host.querySelector<HTMLSelectElement>('[data-task-manager-repeat-kind="3"]')!;
    kind.value = 'weekly';
    kind.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(host.querySelectorAll('[data-task-manager-repeat-day]').length).toBe(7);
    host.querySelector<HTMLElement>('[data-task-manager-repeat-day="4"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-schedule-save="3"]')!.click();
    await settle();
    expect(server.patches.at(-1)!.body).toEqual({ repeat: { freq: 'weekly', byweekday: [0, 1, 2, 3], time: '09:15' }, expected_revision: 3 });

    host.querySelector<HTMLElement>('[data-task-manager-schedule-edit="3"]')?.click();
    openRowMenu(host, 3);
    await settle();
    menuNode('schedule')!.click();
    await settle();
    const again = host.querySelector<HTMLSelectElement>('[data-task-manager-repeat-kind="3"]')!;
    again.value = 'hours';
    again.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    const hours = host.querySelector<HTMLInputElement>('[data-task-manager-repeat-hours="3"]')!;
    hours.value = '6';
    hours.dispatchEvent(new Event('input', { bubbles: true }));
    host.querySelector<HTMLElement>('[data-task-manager-schedule-save="3"]')!.click();
    await settle();
    const body = server.patches.at(-1)!.body;
    expect(body.repeat).toEqual({ freq: 'hourly', interval: 6 });
    expect(typeof body.fire_at).toBe('string');
  });

  test('a repeating row wears the repeat icon, its next time and its repeat; paused says so; pause and stop PATCH', async () => {
    const soon = Date.now() / 1000 + 3 * 3600;
    server.items = [
      mk(1, { start_trigger: trigger(soon, { repeat: { freq: 'weekly', byweekday: [0, 1, 2, 3, 4], time: '09:00' }, paused: false }) }),
      mk(2, { start_trigger: trigger(soon, { repeat: { freq: 'daily', time: '09:00' }, paused: true }) }),
      mk(3),
    ];
    const host = await mountBody();
    const row = host.querySelector<HTMLElement>('[data-task-manager-due="1"]')!;
    expect(row.dataset.taskManagerDueRepeat).toBe('1');
    expect(row.title).toContain('weekdays 9:00 am');
    expect(row.textContent).toMatch(/(today|tomorrow) \d{1,2}:\d\d (am|pm)/);
    expect(host.querySelector<HTMLElement>('[data-task-manager-due="2"]')!.dataset.dueState).toBe('paused');
    host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-schedule="1"]')!.textContent).toContain('weekdays 9:00 am');
    host.querySelector<HTMLElement>('[data-task-manager-schedule-pause="1"]')!.click();
    await settle();
    expect(server.patches.at(-1)!.body).toEqual({ paused: true, expected_revision: 3 });
    host.querySelector<HTMLElement>('[data-task-manager-schedule-cancel="1"]')!.click();
    await settle();
    expect(server.patches.at(-1)!.body).toEqual({ fire_at: '', expected_revision: 3 });
  });

  test('an item with no schedule shows no schedule control, on the row or in the open body', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="3"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-schedule="3"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-due="3"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-title="3"]')).toBeNull();
  });

  test('a failed fire shows its reason in the open item, and an approved item has no control', async () => {
    server.items = [...server.items, mk(4, { state: 'done', status: 'done', section: 'done' })];
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="2"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-schedule-error="2"]')!.textContent).toBe('could not start a session');
    host.querySelector<HTMLElement>('[data-task-manager-status-fold="done"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-toggle="4"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-schedule="4"]')).toBeNull();
  });
});
