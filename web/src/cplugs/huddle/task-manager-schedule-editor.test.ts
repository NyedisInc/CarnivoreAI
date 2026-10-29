/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ items: [] as unknown[], writes: [] as { path: string; method: string; body: Record<string, unknown> | null }[] }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      if (method !== 'GET') server.writes.push({ path, method, body: init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null });
      if (method === 'POST' && /\/lists\/[^/]+\/items$/.test(path)) return { id: 77 };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [{ key: '12', name: 'proj', project_id: 12, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0, waiting_to_send: 0, incomplete: 2 }] };
      }
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: '12', revision: 9, cursor: 9, groups: [], items: server.items };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { closeScheduleEditor } from './task-manager-schedule-editor.svelte';
import { addBody, editBody, editorDraft } from './task-manager-schedule';
import type { HuddleItem } from './huddle-model';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;
const trigger = (fire_at: number, extra: Record<string, unknown> = {}) => ({ kind: 'at', fire_at, fired_at: null, last_error: null, ...extra });
const mk = (id: number, extra: Record<string, unknown> = {}) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: id, revision: 3, created_seq: id,
  seq: id, deleted: false, thread: [], unread: false, group: null, status: 'open', section: 'open', start_trigger: null, ...extra,
});

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

async function type(host: HTMLElement, selector: string, value: string, event = 'input'): Promise<void> {
  const el = host.querySelector<HTMLInputElement>(selector)!;
  el.value = value;
  el.dispatchEvent(new Event(event, { bubbles: true }));
  await settle();
}

const click = async (host: HTMLElement, selector: string): Promise<void> => {
  host.querySelector<HTMLElement>(selector)!.click();
  await settle();
};

beforeEach(() => {
  server.writes = [];
  huddle.selected = '12';
  huddle.openId = null;
  const soon = Date.now() / 1000 + 3 * 3600;
  server.items = [mk(1, { start_trigger: trigger(soon), title: 'nightly' }), mk(2)];
});

afterEach(() => {
  closeScheduleEditor();
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the bodies', () => {
  const item = (extra: Record<string, unknown>) => mk(5, extra) as unknown as HuddleItem;

  test('an edit sends only what changed, and an untouched schedule is never re-sent', () => {
    const scheduled = item({ title: 'a', start_trigger: trigger(Date.now() / 1000 + 3600) });
    const draft = editorDraft(scheduled, new Date());
    expect(editBody(scheduled, draft, true)).toEqual({});
    expect(editBody(scheduled, { ...draft, text: 'new words' }, true)).toEqual({ text: 'new words' });
    expect(editBody(scheduled, { ...draft, title: 'b', text: 'x' }, true)).toEqual({ title: 'b', text: 'x' });
    const daily = editBody(scheduled, { ...draft, plan: { ...draft.plan, kind: 'daily' } }, true);
    expect(daily).toMatchObject({ repeat: { freq: 'daily' } });
  });

  test('an unscheduled item run now does not arm a schedule, and an invalid schedule is refused', () => {
    const plain = item({});
    const draft = { ...editorDraft(plain, new Date()), text: 'changed' };
    expect(editBody(plain, draft, false)).toEqual({ text: 'changed' });
    expect(editBody(plain, draft, true)).toMatchObject({ text: 'changed', fire_at: expect.any(String) });
    expect(editBody(plain, { ...draft, when: '' }, true)).toBeNull();
    expect(editBody(plain, { ...draft, plan: { ...draft.plan, kind: 'weekly', days: [] } }, true)).toBeNull();
  });

  test('a new item needs instructions; armed it carries the time and the repeat', () => {
    const draft = { ...editorDraft(null, new Date()), text: 'check the build', title: ' ' };
    expect(addBody({ ...draft, text: '  ' }, true)).toBeNull();
    expect(addBody(draft, false)).toEqual({ text: 'check the build' });
    const armed = addBody({ ...draft, plan: { ...draft.plan, kind: 'daily' } }, true)!;
    expect(armed).toMatchObject({ text: 'check the build', repeat: { freq: 'daily' } });
    expect(typeof armed.fire_at).toBe('string');
  });
});

describe('the editor', () => {
  test('"+ schedule" on the scheduled header adds an item with instructions, a time and a repeat', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-schedule-add="12"]');
    expect(host.querySelector('[data-task-manager-schedule-editor="new"]')).not.toBeNull();
    await type(host, '[data-task-manager-schedule-title="new"]', 'nightly check');
    await type(host, '[data-task-manager-schedule-text="new"]', 'run the nightly check and report');
    await type(host, '[data-task-manager-schedule-input="new"]', '2026-12-24T09:15');
    await type(host, '[data-task-manager-repeat-kind="new"]', 'daily', 'change');
    await click(host, '[data-task-manager-schedule-save="new"]');
    const add = server.writes.find((w) => w.method === 'POST')!;
    expect(add.path).toBe('/cplugs/huddle/lists/12/items');
    expect(add.body).toMatchObject({ text: 'run the nightly check and report', title: 'nightly check', repeat: { freq: 'daily', time: '09:15' } });
    expect(new Date(String(add.body!.fire_at)).getTime()).toBe(new Date(2026, 11, 24, 9, 15).getTime());
    expect(host.querySelector('[data-task-manager-schedule-editor]')).toBeNull();
  });

  test('a new item with blank instructions writes nothing and stays open', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-schedule-add="12"]');
    await click(host, '[data-task-manager-schedule-save="new"]');
    expect(server.writes).toEqual([]);
    expect(host.querySelector('[data-task-manager-schedule-editor="new"]')).not.toBeNull();
  });

  test('the time of a scheduled item opens the editor on it: change the instructions and the time in one PATCH', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-toggle="1"]');
    await click(host, '[data-task-manager-schedule-edit="1"]');
    const text = host.querySelector<HTMLTextAreaElement>('[data-task-manager-schedule-text="1"]')!;
    expect(text.value).toBe('item 1');
    expect(host.querySelector<HTMLInputElement>('[data-task-manager-schedule-title="1"]')!.value).toBe('nightly');
    await type(host, '[data-task-manager-schedule-text="1"]', 'do it differently');
    await type(host, '[data-task-manager-schedule-input="1"]', '2026-12-24T09:15');
    await click(host, '[data-task-manager-schedule-save="1"]');
    const patch = server.writes.at(-1)!;
    expect(patch.method).toBe('PATCH');
    expect(patch.path).toBe('/cplugs/huddle/items/1');
    expect(patch.body).toMatchObject({ text: 'do it differently', expected_revision: 3 });
    expect(new Date(String(patch.body!.fire_at)).getTime()).toBe(new Date(2026, 11, 24, 9, 15).getTime());
    expect(patch.body).not.toHaveProperty('title');
  });

  test('saving with nothing changed writes nothing', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-toggle="1"]');
    await click(host, '[data-task-manager-schedule-edit="1"]');
    await click(host, '[data-task-manager-schedule-save="1"]');
    expect(server.writes).toEqual([]);
    expect(host.querySelector('[data-task-manager-schedule-editor]')).toBeNull();
  });

  test('run now on a scheduled item saves the edit, then POSTs run-now', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-toggle="1"]');
    await click(host, '[data-task-manager-schedule-edit="1"]');
    await type(host, '[data-task-manager-schedule-text="1"]', 'go now with this');
    await click(host, '[data-task-manager-schedule-run="1"]');
    expect(server.writes.map((w) => `${w.method} ${w.path}`)).toEqual(['PATCH /cplugs/huddle/items/1', 'POST /cplugs/huddle/items/1/run-now']);
    expect(server.writes[0]!.body).toEqual({ text: 'go now with this', expected_revision: 3 });
    expect(host.querySelector('[data-task-manager-schedule-editor]')).toBeNull();
  });

  test('run now on a new one-off item adds it unscheduled, then fires it', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-schedule-add="12"]');
    await type(host, '[data-task-manager-schedule-text="new"]', 'just do this now');
    await click(host, '[data-task-manager-schedule-run="new"]');
    expect(server.writes.map((w) => `${w.method} ${w.path}`)).toEqual(['POST /cplugs/huddle/lists/12/items', 'POST /cplugs/huddle/items/77/run-now']);
    expect(server.writes[0]!.body).toEqual({ text: 'just do this now' });
  });

  test('the item menu opens the editor on an unscheduled item, and Escape closes it without a write', async () => {
    const host = await mountBody();
    await click(host, '[data-task-manager-toggle="2"]');
    await click(host, '[data-task-manager-move-open="2"]');
    await click(host, '[data-task-manager-menu-schedule="2"]');
    const editor = host.querySelector<HTMLElement>('[data-task-manager-schedule-editor="2"]')!;
    expect(editor).not.toBeNull();
    editor.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(host.querySelector('[data-task-manager-schedule-editor]')).toBeNull();
    expect(server.writes).toEqual([]);
  });
});
