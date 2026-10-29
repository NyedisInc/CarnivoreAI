/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ writes: [] as { path: string; method: string; body: Record<string, unknown> | null }[], scheduled: false }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  const row = (key: string, name: string | null, project_id: number | null) => ({ key, name, project_id, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0, incomplete: 1 });
  const item = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
    id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: id, revision: 3, created_seq: id,
    seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', start_trigger: null, ...extra });
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (method !== 'GET') server.writes.push({ path, method, body: init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null });
      if (method === 'POST' && /\/lists\/[^/]+\/items$/.test(path)) return { id: 77 };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [row('all', null, null), row('12', 'alpha', 12), row('18', 'beta', 18)] };
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        const fire = { kind: 'at', fire_at: Date.now() / 1000 + 3600, fired_at: null, last_error: null };
        return { cursor: 9, groups: [
          { list: '12', name: 'alpha', project_id: 12, revision: 1, items: [item(1, '12', server.scheduled ? { start_trigger: fire, status: 'scheduled', section: 'scheduled' } : {})] },
          { list: '18', name: 'beta', project_id: 18, revision: 1, items: [item(2, '18')] },
        ] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { closeScheduleEditor } from './task-manager-schedule-editor.svelte';
import { SCHEDULE_PROJECT_KEY, defaultProject, projectChoices } from './task-manager-schedule-project';
import { AGGREGATE } from './huddle-model';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

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

const click = async (host: HTMLElement, selector: string): Promise<void> => {
  host.querySelector<HTMLElement>(selector)!.click();
  await settle();
};

beforeEach(() => {
  server.writes = [];
  server.scheduled = false;
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  localStorage.removeItem(SCHEDULE_PROJECT_KEY);
});

afterEach(() => {
  closeScheduleEditor();
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('defaultProject', () => {
  const lists = [{ key: 'aggregate' }, { key: 'all' }, { key: 'agent:5' }, { key: '12' }, { key: '18' }];

  test('the opened-from project wins, then the remembered one, then the first project before the shared list', () => {
    expect(defaultProject('18', lists, '12')).toBe('18');
    expect(defaultProject(AGGREGATE, lists, '18')).toBe('18');
    expect(defaultProject(AGGREGATE, lists, 'gone')).toBe('12');
    expect(defaultProject(AGGREGATE, lists, null)).toBe('12');
    expect(defaultProject(AGGREGATE, [{ key: 'all' }], null)).toBe('all');
    expect(defaultProject('12', [], null)).toBe('12');
  });

  test('the choices are the shared list and the projects, never all projects or an agent list', () => {
    expect(projectChoices(lists).map((r) => r.key)).toEqual(['all', '12', '18']);
  });
});

describe('the scheduled section with nothing scheduled', () => {
  test('all projects shows the scheduled header, "+ schedule" and the quiet line, once', async () => {
    const host = await mountBody();
    expect(host.querySelectorAll('[data-task-manager-schedule-strip]')).toHaveLength(1);
    expect(host.querySelector('[data-task-manager-schedule-none]')?.textContent).toBe('nothing scheduled');
    const add = host.querySelector('[data-task-manager-schedule-add]');
    expect(add?.textContent?.trim()).toBe('');
    expect(add?.getAttribute('aria-label')).toBe('+ schedule');
    expect(add?.getAttribute('title')).toBe('+ schedule');
  });

  test('all projects with a scheduled item keeps that section\'s own header and draws no second strip', async () => {
    server.scheduled = true;
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-schedule-strip]')).toBeNull();
    expect(host.querySelectorAll('[data-task-manager-schedule-add]')).toHaveLength(1);
  });
});

describe('the editor\'s project picker', () => {
  test('from all projects it defaults to the first project and a pick is remembered for next time', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-schedule-add]');
    const pick = host.querySelector<HTMLSelectElement>('[data-task-manager-schedule-project="new"]')!;
    expect(pick.value).toBe('12');
    expect([...pick.options].map((o) => o.textContent)).toEqual(['shared', 'alpha', 'beta']);
    pick.value = '18';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(localStorage.getItem(SCHEDULE_PROJECT_KEY)).toBe('18');
    const text = host.querySelector<HTMLTextAreaElement>('[data-task-manager-schedule-text="new"]')!;
    text.value = 'check beta';
    text.dispatchEvent(new Event('input', { bubbles: true }));
    await click(host, '[data-task-manager-schedule-save="new"]');
    expect(server.writes.find((w) => w.method === 'POST')?.path).toBe('/cplugs/huddle/lists/18/items');
    await click(host, '[data-task-manager-schedule-add]');
    expect(host.querySelector<HTMLSelectElement>('[data-task-manager-schedule-project="new"]')!.value).toBe('18');
  });

  test('an existing item shows its project read-only', async () => {
    server.scheduled = true;
    const host = await mountBody();
    await click(host, '[data-task-manager-toggle="1"]');
    await click(host, '[data-task-manager-schedule-edit="1"]');
    expect(host.querySelector('[data-task-manager-schedule-project]')).toBeNull();
    expect(host.querySelector('[data-task-manager-schedule-project-fixed="1"]')?.textContent).toBe('alpha');
  });
});
