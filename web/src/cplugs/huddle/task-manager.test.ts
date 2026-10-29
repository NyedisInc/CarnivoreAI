/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

type Call = { path: string; method: string; body: unknown };

const server = vi.hoisted(() => ({
  calls: [] as Call[],
  lists: [] as Record<string, unknown>[],
  body: null as Record<string, unknown> | null,
  groups: [] as Record<string, unknown>[],
  sessions: [] as Record<string, unknown>[],
  sendDefault: null as string | null,
  sendReason: 'pick',
  prefs: { revision: 3, settings: { hideCompleted: false, view: 'area' } as Record<string, unknown> },
  prefsStale: false,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: init.body ? JSON.parse(String(init.body)) : null });
      if (path === '/cplugs/huddle' && method === 'PUT') {
        const body = JSON.parse(String(init.body));
        if (server.prefsStale) {
          server.prefsStale = false;
          server.prefs.revision += 1;
          throw new real.ApiError('stale', 409, 'stale_revision', { detail: { code: 'stale_revision', current: structuredClone(server.prefs) } });
        }
        if (body.revision !== server.prefs.revision) throw new real.ApiError('stale', 409, 'stale_revision', { detail: { code: 'stale_revision' } });
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return structuredClone(server.prefs);
      }
      if (path === '/cplugs/huddle') return structuredClone(server.prefs);
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: structuredClone(server.lists) };
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 9, groups: structuredClone(server.groups) };
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return structuredClone(server.body);
      if (path.endsWith('/sessions')) return { sessions: server.sessions, default: server.sendDefault, reason: server.sendReason };
      if (path === '/cplugs/huddle/send') {
        const body = JSON.parse(String(init.body)) as { lists: string[]; targets: Record<string, string> };
        return { results: body.lists.map((list) => (body.targets[list] || server.sendDefault
          ? { list, status: 'sent', target: body.targets[list] ?? server.sendDefault, label: 'agent' }
          : { list, status: 'no_session', sessions: server.sessions })) };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager, selectList } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs, setShowTab } from './task-manager-prefs.svelte';
import { reloadTaskManagerUi } from './task-manager-ui.svelte';
import { AGGREGATE, listFromSearch } from './huddle-model';
import { taskManagerTab } from './task-manager-tab';
import { tabPath } from '../../lib/dynamic-tabs/tab-popout';
import { sidebarTabs } from '../sdk';
import '../../lib/dynamic-tabs/builtin';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

// Task Manager is on by default for a clean install since 2026-10-05 (docs/cplugs.md section 9 question 1, superseded);
// these tests pin its enablement explicitly instead of leaning on the default.
cplugEnablement.enabled = { huddle: true };
import { resetSendPicks, sendPicks } from './huddle-send-many.svelte';
import { setSectionFolded } from './task-manager-status-folds.svelte';

function item(id: number, over: Record<string, unknown> = {}) {
  return {
    id, list: 'all', text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open',
    revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...over,
  };
}

function listRow(over: Record<string, unknown> = {}) {
  return { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, ...over };
}

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

beforeEach(async () => {
  localStorage.clear();
  sessionStorage.clear();
  reloadTaskManagerUi();
  server.calls = [];
  server.lists = [listRow()];
  server.body = { list: 'all', revision: 7, cursor: 7, items: [item(1), item(2, { created_by: 'claude', state: 'review' }), item(3)] };
  server.sessions = [];
  server.sendDefault = null;
  resetSendPicks();
  setSectionFolded('none:done', false); // the area view's done subsection starts folded; these tests read checked rows
  huddle.selected = 'all';
  huddle.body = null;
  huddle.groups = null;
  server.groups = [];
  server.prefs = { revision: 3, settings: { hideCompleted: false, view: 'area' } };
  taskManagerPrefs.showTab = true;
  huddle.openId = null;
  huddle.addTarget = 'all';
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

async function mountBody(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: true } });
  await settle();
  return host;
}

function expand(host: HTMLElement, id: number): void {
  host.querySelector<HTMLElement>(`[data-task-manager-toggle="${id}"]`)?.click();
  flushSync();
}

describe('the list', () => {
  test('no number on screen: each row wears its status mark, named for a reader and in a tooltip (item 43)', async () => {
    server.body = { list: 'all', revision: 1, cursor: 1, items: [
      item(1, { number: 1, status: 'question' }), item(2, { state: 'done', number: null, status: 'done' }),
      item(3, { number: 2, status: 'waiting_to_send' }), item(4, { number: 3, status: 'working' }),
      item(5, { number: 4, status: 'review', state: 'review' }), item(6, { number: 5, status: 'open' })] };
    await refreshTaskManager();
    const host = await mountBody();
    expect(host.querySelector('[data-huddle-number], .hdr-num')).toBeNull();
    const mark = (id: number) => host.querySelector<HTMLElement>(`[data-huddle-item="${id}"] [data-task-manager-status-icon]`)!;
    expect([1, 2, 3, 4, 5, 6].map((id) => mark(id).dataset.taskManagerStatusIcon)).toEqual(['question', 'done', 'open', 'working', 'review', 'open']);
    expect(mark(1).getAttribute('aria-label')).toBe('claude asked: waiting on you');
    expect(mark(1).getAttribute('title')).toBe('claude asked: waiting on you');
    expect(mark(1).style.getPropertyValue('--_icon')).toBe('var(--oc-yellow-bright)');
    expect(mark(4).querySelector('animate, animateTransform')).toBeNull();
    expect(new Set([1, 4, 5, 6].map((id) => mark(id).innerHTML)).size).toBe(4);
  });

  test('rows show the text, the state as a colour with its name for a reader, and only the session-type mark', async () => {
    const g = globalThis as unknown as Record<string, unknown>;
    g.AgentFamilyIcon = { svg: (f: string) => `<svg data-family="${f}"></svg>`, normalize: (f: string) => f, labelFor: (f: string) => f };
    const host = await mountBody();
    delete g.AgentFamilyIcon;
    const rows = [...host.querySelectorAll<HTMLElement>('[data-huddle-item]')];
    expect(rows.map((r) => r.dataset.huddleItem)).toEqual(['2', '1', '3']);
    rows.splice(0, 2, rows[1]!, rows[0]!);
    expect(rows[1]?.querySelector('[data-huddle-chip]')).toBeNull();
    expect(rows[1]?.style.getPropertyValue('--_state')).toBe('var(--oc-cyan)');
    expect(rows[1]?.querySelector('[data-task-manager-state]')?.textContent).toBe('review');
    expect(rows[1]?.querySelector('[data-task-manager-status-icon]')?.getAttribute('title')).toBe('claude says done: waiting on your review');
    const mark = rows[1]?.querySelector('[data-task-manager-by-claude]');
    expect(mark?.getAttribute('data-task-manager-by-claude')).toBe('claude');
    expect(mark?.textContent).toBe('');
    expect(mark?.querySelector('svg')?.getAttribute('data-family')).toBe('claude');
    expect(rows[0]?.querySelector('[data-task-manager-by-claude]')).toBeNull();
    const human = rows[0]?.querySelector('[data-task-manager-by-joe]');
    expect(human?.getAttribute('aria-label')).toBe('you added this');
    expect(human?.querySelector('svg')).not.toBeNull();
    expect(human?.querySelector('svg')?.getAttribute('data-family')).toBeNull();
    expect(rows[1]?.querySelector('[data-task-manager-by-joe]')).toBeNull();
  });

  test('the checkbox approves with the item revision', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-check="2"]')?.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')?.click();
    await settle();
    const call = server.calls.find((c) => c.method === 'PATCH');
    expect(call).toEqual({ path: '/cplugs/huddle/items/2', method: 'PATCH', body: { approved: true, expected_revision: 1 } });
  });

  test('a note is written and saved', async () => {
    const host = await mountBody();
    expand(host, 1);
    host.querySelector<HTMLElement>('[data-task-manager-note-open="1"]')?.click();
    flushSync();
    const input = host.querySelector<HTMLTextAreaElement>('[data-task-manager-note-input="1"]');
    expect(input).not.toBeNull();
    input!.value = 'rename it first';
    input!.dispatchEvent(new Event('input'));
    flushSync();
    host.querySelector<HTMLElement>('[data-task-manager-note-save="1"]')?.click();
    await settle();
    expect(server.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ note: 'rename it first', expected_revision: 1 });
  });

  test('the thread opens and a reply posts to the item', async () => {
    const host = await mountBody();
    expand(host, 3);
    const reply = host.querySelector<HTMLTextAreaElement>('[data-huddle-reply="3"]');
    reply!.value = 'yes, the second one';
    reply!.dispatchEvent(new Event('input'));
    flushSync();
    reply!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await settle();
    expect(server.calls.find((c) => c.method === 'POST')).toEqual({
      path: '/cplugs/huddle/items/3/messages', method: 'POST', body: { text: 'yes, the second one', client_id: expect.any(String) } });
  });

  test('compact: a waiting claude question opens its thread and marks the row', async () => {
    server.prefs.settings.density = 'compact'; // a question opens the row only in compact (docs/task-manager.md section 24)
    await refreshPrefs();
    server.body = { list: 'all', revision: 8, cursor: 8, items: [item(4, { thread: [
      { id: 1, item_id: 4, author: 'claude', kind: 'question', text: 'which one?', answered: false, created_at: 0, seq: 8 }] })] };
    await refreshTaskManager();
    const host = await mountBody();
    expect(host.querySelector('[data-huddle-item="4"]')?.classList.contains('tkm--asking')).toBe(true);
    expect(host.querySelector('[data-task-manager-message="1"]')?.textContent).toContain('which one?');
  });

  test('the grip moves a row inside its status subsection and sends the whole order with the list revision', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-grip="1"]')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    await settle();
    expect(server.calls.find((c) => c.method === 'PUT')).toEqual({
      path: '/cplugs/huddle/lists/all/order', method: 'PUT', body: { ids: [3, 2, 1], expected_revision: 7 } });
  });

  test('the add box adds to the list on screen', async () => {
    await selectList('all');
    const host = await mountBody();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-add]');
    input!.value = 'fix this';
    input!.dispatchEvent(new Event('input'));
    flushSync();
    input!.form!.dispatchEvent(new Event('submit', { cancelable: true }));
    await settle();
    expect(server.calls.find((c) => c.method === 'POST')).toEqual({ path: '/cplugs/huddle/lists/all/inbox', method: 'POST', body: { text: 'fix this', client_id: expect.any(String) } });
  });
});

describe('the tab setting (#1343)', () => {
  test('the tab is shown by default with no close key, the toggle hides it, and another browser follows', async () => {
    sidebarTabs.select('agents');
    server.prefs = { revision: 3, settings: {} };
    await refreshPrefs();
    expect(taskManagerPrefs.showTab).toBe(true);
    expect(sidebarTabs.present().some((d) => d.id === 'huddle')).toBe(true);
    expect(taskManagerTab.close).toBeUndefined();
    sidebarTabs.close('huddle');
    expect(sidebarTabs.present().some((d) => d.id === 'huddle')).toBe(true);
    server.lists = [listRow({ claude_seq: 5, questions: 1 })];
    await refreshTaskManager();
    expect(sidebarTabs.active()).toBe('agents');

    expect(await setShowTab(false)).toBe(true);
    expect(server.calls.find((c) => c.method === 'PUT')?.body).toEqual({ revision: 3, settings: { showTab: false } });
    expect(sidebarTabs.present().some((d) => d.id === 'huddle')).toBe(false);
    server.lists = [listRow({ claude_seq: 6, questions: 1 })];
    await refreshTaskManager();
    expect(sidebarTabs.present().some((d) => d.id === 'huddle')).toBe(false);

    server.prefs = { revision: 9, settings: { showTab: true } };
    await refreshPrefs();
    expect(sidebarTabs.present().some((d) => d.id === 'huddle')).toBe(true);
  });
});

describe('the open item: a chat under the description (item 42)', () => {
  const thread = Array.from({ length: 6 }, (_, n) => ({
    id: n + 1, item_id: 3, author: n % 2 ? 'joe' : 'claude', kind: n === 2 ? 'info' : n === 4 ? 'attention' : n % 2 ? 'reply' : 'question',
    text: `message ${n + 1}`, answered: true, created_at: 1_700_000_000 + n * 60, seq: n + 1,
  }));

  test('the description stays as is; the thread sits under it in its own box, claude left and joe right, each tagged', async () => {
    server.body = { list: 'all', revision: 7, cursor: 7, items: [item(3, { text: 'the original description', thread })] };
    await refreshTaskManager();
    const host = await mountBody();
    expand(host, 3);
    expect(host.querySelector('[data-task-manager-description="3"]')?.textContent).toBe('the original description');
    const box = host.querySelector<HTMLElement>('[data-task-manager-thread-box="3"]')!;
    expect(box).not.toBeNull();
    expect(box.dataset.taskManagerThreadNewest).toBe('6');
    const messages = [...box.querySelectorAll<HTMLElement>('[data-task-manager-message]')];
    expect(messages.map((m) => m.dataset.by)).toEqual(['claude', 'joe', 'claude', 'joe', 'claude', 'joe']);
    expect(messages[0]!.classList.contains('hdt-msg--claude')).toBe(true);
    expect(messages[1]!.classList.contains('hdt-msg--joe')).toBe(true);
    expect(messages.map((m) => m.querySelector('[data-hb-kind]')?.getAttribute('data-hb-kind') ?? null))
      .toEqual(['question', null, 'info', null, 'look', null]);
    expect(messages.every((m) => m.querySelector('time') && m.querySelector('.hb-who'))).toBe(true);
    expect(box.querySelector('[data-huddle-reply]')).toBeNull();
  });

  test('opening the item, and a new message, scroll the box to the newest', async () => {
    const tops: number[] = [];
    const proto = HTMLElement.prototype as unknown as Record<string, unknown>;
    const scrollTop = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollTop');
    const scrollHeight = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollHeight');
    Object.defineProperty(proto, 'scrollHeight', { configurable: true, get() { return 100 * this.querySelectorAll('[data-task-manager-message]').length; } });
    Object.defineProperty(proto, 'scrollTop', { configurable: true, get() { return 0; }, set(v: number) { if (this.dataset.taskManagerThreadBox) tops.push(v); } });
    try {
      server.body = { list: 'all', revision: 7, cursor: 7, items: [item(3, { thread: thread.slice(0, 5) })] };
      await refreshTaskManager();
      const host = await mountBody();
      expand(host, 3);
      await settle();
      expect(tops.at(-1)).toBe(500);
      server.body = { list: 'all', revision: 8, cursor: 8, items: [item(3, { thread })] };
      await refreshTaskManager();
      await settle();
      expect(tops.at(-1)).toBe(600);
    } finally {
      delete proto.scrollTop;
      delete proto.scrollHeight;
      if (scrollTop) Object.defineProperty(Element.prototype, 'scrollTop', scrollTop);
      if (scrollHeight) Object.defineProperty(Element.prototype, 'scrollHeight', scrollHeight);
    }
  });
});

describe('a reply whose list has no session to tell (item 44)', () => {
  test('a list with no default has no picker on the reply box; the send key pop-up is where it is picked', async () => {
    server.sessions = [{ id: 'ses_a', label: 'a' }, { id: 'ses_b', label: 'b' }];
    server.sendDefault = null;
    const host = await mountBody();
    expand(host, 3);
    await settle();
    expect(host.querySelector('[data-huddle-reply-target]')).toBeNull();
    expect(host.querySelector('[data-huddle-reply="3"]')!.classList.contains('hdt-input--wide')).toBe(false);
  });

  test('a list with a default shows no picker', async () => {
    server.sessions = [{ id: 'ses_a', label: 'a' }];
    server.sendDefault = 'ses_a';
    const host = await mountBody();
    expand(host, 3);
    await settle();
    expect(host.querySelector('[data-huddle-reply-target]')).toBeNull();
  });
});

describe('the pop-out opens on the list the sidebar showed', () => {
  test('the pop out key carries the list on screen into the URL, and the window reads it back', () => {
    huddle.selected = '18';
    const params = taskManagerTab.popoutParams?.() ?? {};
    expect(params).toEqual({ list: '18' });
    expect(tabPath('huddle', params)).toBe('/static/popout.html?tab=huddle&list=18');
    expect(listFromSearch('?tab=huddle&list=18')).toBe('18');
    expect(listFromSearch('?tab=huddle&list=aggregate')).toBe(AGGREGATE);
    expect(listFromSearch('?tab=huddle&list=../x')).toBeNull();
    expect(listFromSearch('?tab=huddle')).toBeNull();
    expect(tabPath('huddle')).toBe('/static/popout.html?tab=huddle');
  });
});

describe('all projects is an aggregate', () => {
  const group = (list: string, name: string | null, ids: number[], revision: number) => ({
    list, name, project_id: list === 'all' ? null : Number(list), revision, items: ids.map((id) => item(id, { list })) });

  beforeEach(async () => {
    server.lists = [listRow(), listRow({ key: '18', name: 'CloudeCode', project_id: 18 })];
    server.groups = [group('all', null, [1], 3), group('18', 'CloudeCode', [11, 12, 13, 14, 15], 20)];
    huddle.selected = AGGREGATE;
    huddle.groups = null;
    await refreshTaskManager();
  });

  test('every project shows under its heading, the shared list first', async () => {
    const host = await mountBody();
    expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-heading]')].map((h) => [h.dataset.taskManagerHeading, h.textContent])).toEqual([
      ['all', 'shared'], ['18', 'CloudeCode']]);
    expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-group="18"] [data-huddle-item]')].map((r) => r.dataset.huddleItem))
      .toEqual(['11', '12', '13', '14', '15']);
    expect(host.querySelector('[data-task-manager-empty]')).toBeNull();
  });

  test('an action works per item and a reorder stays inside its group with that group\'s revision', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-check="12"]')?.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-tick-confirm-yes]')?.click();
    await settle();
    expect(server.calls.find((c) => c.method === 'PATCH')?.path).toBe('/cplugs/huddle/items/12');
    host.querySelector<HTMLElement>('[data-task-manager-grip="11"]')?.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
    await settle();
    expect(server.calls.find((c) => c.method === 'PUT')).toEqual({
      path: '/cplugs/huddle/lists/18/order', method: 'PUT', body: { ids: [12, 11, 13, 14, 15], expected_revision: 20 } });
  });

  test('an add goes to the shared list unless a project group is chosen', async () => {
    const host = await mountBody();
    const input = host.querySelector<HTMLInputElement>('[data-task-manager-add]');
    const submit = async (text: string) => {
      input!.value = text;
      input!.dispatchEvent(new Event('input'));
      flushSync();
      input!.form!.dispatchEvent(new Event('submit', { cancelable: true }));
      await settle();
    };
    await submit('to shared');
    expect(server.calls.filter((c) => c.method === 'POST' && !c.path.endsWith('/send')).at(-1)?.path).toBe('/cplugs/huddle/lists/all/inbox');
    const pick = host.querySelector<HTMLSelectElement>('[data-task-manager-add-target]');
    pick!.value = '18';
    pick!.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    await submit('to project');
    expect(server.calls.filter((c) => c.method === 'POST' && !c.path.endsWith('/send')).at(-1)).toEqual({
      path: '/cplugs/huddle/lists/18/inbox', method: 'POST', body: { text: 'to project', client_id: expect.any(String) } });
  });

});

describe('the accordion and kinds', () => {
  test('a row is collapsed to one line until its summary is toggled, and the toggle is a real button', async () => {
    const host = await mountBody();
    const toggle = host.querySelector<HTMLElement>('[data-task-manager-toggle="1"]')!;
    expect(toggle.tagName).toBe('BUTTON');
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(host.querySelector('[data-task-manager-detail="1"]')).toBeNull();
    expect(host.querySelector('[data-huddle-item="1"] .tkm-text--clip2')).not.toBeNull();
    toggle.click();
    flushSync();
    expect(toggle.getAttribute('aria-expanded')).toBe('true');
    expect(host.querySelector('[data-task-manager-detail="1"]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="1"] .tkm-text--clip2')).toBeNull();
    toggle.click();
    flushSync();
    expect(host.querySelector('[data-task-manager-detail="1"]')).toBeNull();
  });

  test('the sidebar previews one line', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout: false } });
    await settle();
    expect(host.querySelector('[data-huddle-item="1"] .tkm-text--clip')).not.toBeNull();
    expect(host.querySelector('[data-huddle-item="1"] .tkm-text--clip2')).toBeNull();
  });

  test('one row opens at a time: opening another closes the last', async () => {
    const host = await mountBody();
    expand(host, 1);
    expect(host.querySelector('[data-task-manager-detail="1"]')).not.toBeNull();
    expand(host, 3);
    expect(host.querySelector('[data-task-manager-detail="3"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-detail="1"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-toggle="1"]')?.getAttribute('aria-expanded')).toBe('false');
  });

});

describe('completed items, the add box and the opening list (Joe, 2026-10-03)', () => {
  const done = () => {
    server.body = { list: 'all', revision: 7, cursor: 7, items: [item(1), item(2, { state: 'done' }), item(3, { state: 'done', note: 'n' }), item(4)] };
  };

  test('hide completed is off by default; turning it on hides checked rows and stores the setting', async () => {
    done();
    await refreshTaskManager();
    const host = await mountBody();
    const chip = host.querySelector<HTMLElement>('[data-task-manager-hide-completed]')!;
    expect(chip.getAttribute('aria-pressed')).toBe('false');
    expect(host.querySelectorAll('[data-huddle-item]').length).toBe(4);
    chip.click();
    await settle();
    expect(server.calls.find((c) => c.method === 'PUT' && c.path === '/cplugs/huddle')?.body).toEqual({ revision: 3, settings: { hideCompleted: true } });
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect([...host.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((r) => r.dataset.huddleItem)).toEqual(['1', '4']);
    server.body = { list: 'all', revision: 8, cursor: 8, items: [item(1), item(2), item(3, { state: 'done', note: 'n' }), item(4)] };
    await refreshTaskManager();
    flushSync();
    expect([...host.querySelectorAll<HTMLElement>('[data-huddle-item]')].map((r) => r.dataset.huddleItem)).toEqual(['1', '2', '4']);
  });

  test('a stale setting revision is adopted and the change replayed once', async () => {
    server.prefsStale = true;
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-hide-completed]')!.click();
    await settle();
    const puts = server.calls.filter((c) => c.method === 'PUT' && c.path === '/cplugs/huddle');
    expect(puts.map((c) => (c.body as { revision: number }).revision)).toEqual([3, 4]);
    expect(taskManagerPrefs.hideCompleted).toBe(true);
  });

  test('remove completed asks first, then removes the checked items of the list', async () => {
    done();
    await refreshTaskManager();
    const host = await mountBody();
    const button = host.querySelector<HTMLElement>('[data-task-manager-remove-completed]')!;
    expect(button.getAttribute('aria-label')).toBe('remove completed (2)');
    button.click();
    flushSync();
    expect(server.calls.some((c) => c.path.endsWith('/remove-completed'))).toBe(false);
    host.querySelector<HTMLElement>('[data-task-manager-remove-confirm]')!.click();
    await settle();
    expect(server.calls.find((c) => c.path.endsWith('/remove-completed'))).toEqual({
      path: '/cplugs/huddle/lists/all/remove-completed', method: 'POST', body: null });
  });

  test('no completed items, no remove button', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-remove-completed]')).toBeNull();
  });

  test('the add box is one line by default; multiline sends the whole text as one entry (R55), with the one-line placeholder', async () => {
    const host = await mountBody();
    const line = host.querySelector<HTMLInputElement>('[data-task-manager-add]')!;
    expect(line.tagName).toBe('INPUT');
    const closed = line.getAttribute('placeholder');
    expect(closed).toBeTruthy();
    host.querySelector<HTMLElement>('[data-task-manager-multiline]')!.click();
    flushSync();
    const area = host.querySelector<HTMLTextAreaElement>('[data-task-manager-add]')!;
    expect(area.tagName).toBe('TEXTAREA');
    expect(area.getAttribute('placeholder')).toBe(closed);
    expect(area.getAttribute('aria-label')).toBe(closed);
    area.value = 'first\n\n second \nthird';
    area.dispatchEvent(new Event('input'));
    flushSync();
    area.form!.dispatchEvent(new Event('submit', { cancelable: true }));
    await settle();
    expect(server.calls.filter((c) => c.method === 'POST' && !c.path.endsWith('/send')).map((c) => c.body)).toEqual([{ text: 'first\n\n second \nthird', client_id: expect.any(String) }]);
  });

  test('the sidebar opens on the current tab\'s project, for the list and the add box', async () => {
    server.lists = [listRow(), listRow({ key: '18', name: 'CloudeCode', project_id: 18 })];
    await refreshTaskManager();
    huddle.selected = AGGREGATE;
    huddle.addTarget = 'all';
    const g = globalThis as unknown as Record<string, unknown>;
    g.TerminalController = { _currentSession: { id: 'ses_a' } };
    g.ListingPush = { rows: () => [{ session: { id: 'ses_a' }, project_id: 18 }] };
    try {
      const host = document.createElement('div');
      document.body.appendChild(host);
      app = mount(HuddleBody, { target: host, props: { popout: false } });
      await settle();
      expect(huddle.selected).toBe('18');
      expect(huddle.addTarget).toBe('18');
      expect(server.calls.some((c) => c.path === '/cplugs/huddle/lists/18?live_only=1')).toBe(true);
    } finally {
      delete g.TerminalController;
      delete g.ListingPush;
    }
  });
});
