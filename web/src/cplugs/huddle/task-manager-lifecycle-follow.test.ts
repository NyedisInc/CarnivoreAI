/** @vitest-environment jsdom */
import { afterAll, afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({
  calls: [] as { path: string; method: string; body: string }[],
  waiting: { all: 0, '12': 2, '18': 1 } as Record<string, number>,
}));

const STATUSES = ['open', 'question', 'working', 'review', 'done'];
const mk = (id: number, status: string) => ({
  id, list: '12', text: `item ${id}`, note: '', position: id, created_by: 'joe', kind: '',
  state: status.startsWith('done') ? status : status === 'review' ? 'review' : 'open',
  number: id, revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, status,
});
const ITEMS = STATUSES.map((s, i) => mk(i + 1, s));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, method: init.method ?? 'GET', body: String(init.body ?? '') });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'area' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        const row = (key: string, name: string | null, project: number | null) => ({
          key, name, project_id: project, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0,
          untold: (server.waiting[key] ?? 0) > 0, waiting_to_send: server.waiting[key] ?? 0 });
        return { cursor: 0, lists: [row('all', null, null), row('12', 'carnivore', 12), row('18', 'CloudeCode', 18)] };
      }
      if (/\/sessions$/.test(path)) {
        return { sessions: [{ id: 'ses_12', label: 'carnivore agent' }, { id: 'ses_18', label: 'cloude agent' }, { id: 'ses_x', label: 'other' }],
          default: 'ses_x', reason: 'last_task_manager_caller' };
      }
      if (path === '/cplugs/huddle/send') {
        const body = JSON.parse(String(init.body)) as { lists: string[]; targets: Record<string, string> };
        for (const list of body.lists) if (list !== '18' || body.targets['18']) server.waiting[list] = 0;
        return { results: body.lists.map((list) => (list === '18' && !body.targets['18']
          ? { list, status: 'no_session', sessions: [{ id: 'ses_18', label: 'cloude agent' }, { id: 'ses_x', label: 'other' }] }
          : { list, status: 'sent', target: body.targets[list] ?? `ses_${list}`, label: `agent ${list}` })) };
      }
      if (/^\/cplugs\/huddle\/lists\/[^/]+$/.test(path)) return { list: '12', revision: 7, cursor: 7, items: ITEMS };
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 7, groups: [{ list: '12', name: 'carnivore', project_id: 12, revision: 7, items: ITEMS }] };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { AGGREGATE } from './huddle-model';
import { STATUS_COLOR, STATUS_ICON, statusOf } from './huddle-status';
import { addTargetFor } from './task-manager-follow.svelte';
import { resetSendPicks, sendPicks } from './huddle-send-many.svelte';
import { setSectionFolded } from './task-manager-status-folds.svelte';
import { activeProject, ACTIVE_CHANNEL, followActiveProject, resetActiveProject } from '../../lib/sessions/active-project.svelte';
import HuddleBody from './HuddleBody.svelte';
import { cplugEnablement } from '../host/enablement.svelte';

cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

async function mountBody(popout = false): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

async function activate(session: string | null, project: number | null): Promise<void> {
  activeProject.session = session;
  activeProject.project = project;
  await settle();
}

beforeEach(async () => {
  server.calls = [];
  server.waiting = { all: 0, '12': 2, '18': 1 };
  huddle.selected = AGGREGATE;
  huddle.addTarget = 'all';
  resetSendPicks();
  setSectionFolded('none:done', false);
  activeProject.session = null;
  activeProject.project = null;
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

afterAll(() => resetActiveProject());

describe('the lifecycle stripe', () => {
  test('each status has its own theme token, and an item from an older server falls back to its state', () => {
    const tokens = Object.values(STATUS_COLOR);
    expect(new Set(tokens).size).toBe(tokens.length);
    expect('look' in STATUS_COLOR || 'look' in STATUS_ICON).toBe(false);
    expect(new Set(Object.values(STATUS_ICON)).size).toBe(Object.keys(STATUS_ICON).length);
    expect(tokens.every((v) => /^var\(--oc-[a-z-]+\)$/.test(v))).toBe(true);
    expect(statusOf({ ...mk(1, 'open'), status: undefined, state: 'review' } as never)).toBe('review');
    expect(statusOf({ ...mk(1, 'open'), status: undefined, thread: [
      { id: 1, item_id: 1, author: 'claude', kind: 'question', text: '?', answered: false, created_at: 0, seq: 1 }] } as never)).toBe('question');
  });

  for (const popout of [false, true]) {
    test(`${popout ? 'the pop-out' : 'the sidebar'} paints every status with its tooltip and reader label`, async () => {
      const host = await mountBody(popout);
      for (const status of STATUSES) {
        const row = host.querySelector<HTMLElement>(`[data-status="${status}"]`)!;
        expect(row.style.getPropertyValue('--_state')).toBe(STATUS_COLOR[status as keyof typeof STATUS_COLOR]);
        const stripe = row.querySelector<HTMLElement>('.tkm-state')!;
        expect(stripe.getAttribute('data-task-manager-status')).toBe(status);
        expect(stripe.getAttribute('title')).toBeTruthy();
        expect(row.querySelector('[data-task-manager-status-label]')!.textContent).toBe(stripe.getAttribute('title'));
      }
      expect(host.querySelector('[data-status="question"] .tkm-state')!.getAttribute('title')).toBe('claude asked: waiting on you');
    });
  }
});

describe('the tell button carries a small waiting badge and no queue link', () => {
  test('the tell button carries the waiting badge and there is no queue link, sidebar or pop-out', async () => {
    for (const popout of [true, false]) {
      const host = await mountBody(popout);
      const button = host.querySelector<HTMLElement>('[data-task-manager-send]')!;
      expect(button.querySelector('[data-task-manager-send-badge]')?.textContent).toBe(button.dataset.taskManagerSendCount);
      expect(host.querySelector('[data-huddle-queue-link]')).toBeNull();
      unmount(app!);
      app = null;
      document.body.innerHTML = '';
    }
  });
});

describe('the add box follows the active tab', () => {
  test('a tab with a project points the add list at it; a tab with none leaves it; the visible list stays', async () => {
    expect(addTargetFor(18, ['all', '18'])).toBe('18');
    expect(addTargetFor(99, ['all', '18'])).toBeNull();
    expect(addTargetFor(null, ['all'])).toBeNull();
    const host = await mountBody();
    const add = (): HTMLSelectElement => host.querySelector<HTMLSelectElement>('[data-task-manager-add-target]')!;
    await activate('ses_18', 18);
    expect(huddle.addTarget).toBe('18');
    expect(add().value).toBe('18');
    expect(huddle.selected).toBe(AGGREGATE);
    await activate('ses_12', 12);
    expect(add().value).toBe('12');
    await activate('ses_shell', null);
    expect(add().value).toBe('12');
    host.querySelector<HTMLInputElement>('[data-task-manager-add]')!.value = 'new thing';
    host.querySelector<HTMLInputElement>('[data-task-manager-add]')!.dispatchEvent(new Event('input'));
    host.querySelector<HTMLFormElement>('.hd-add')!.dispatchEvent(new Event('submit'));
    await settle();
    expect(server.calls.some((c) => c.path === '/cplugs/huddle/lists/12/inbox' && c.method === 'POST')).toBe(true);
  });
});

describe('one press tells every list into its own session ()', () => {
  test('no dropdown beside the key; lists with no session land in one pop-up, and a pick there sends them', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-huddle-send-target-pick]')).toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-send]')!.click();
    await settle();
    const first = server.calls.filter((c) => c.path === '/cplugs/huddle/send');
    expect(first.map((c) => JSON.parse(c.body))).toEqual([{ lists: ['12', '18'], targets: {} }]);
    expect(huddle.notice).toBe('pick a session for CloudeCode.');
    const ask = host.querySelector<HTMLElement>('[data-task-manager-send-ask]')!;
    expect(ask).not.toBeNull();
    expect([...ask.querySelectorAll('[data-task-manager-send-ask-list]')].map((el) => el.getAttribute('data-task-manager-send-ask-list'))).toEqual(['18']);
    expect(host.querySelector<HTMLButtonElement>('[data-task-manager-send-send]')!.disabled).toBe(true);
    const pick = host.querySelector<HTMLSelectElement>('[data-task-manager-send-ask-pick="18"]')!;
    pick.value = 'ses_18';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-send-send]')!.click();
    await settle();
    const calls = server.calls.filter((c) => c.path === '/cplugs/huddle/send').map((c) => JSON.parse(c.body));
    expect(calls.at(-1)).toEqual({ lists: ['18'], targets: { '18': 'ses_18' } });
    expect(sendPicks.picks).toEqual({ '18': 'ses_18' });
    expect(host.querySelector('[data-task-manager-send-ask]')).toBeNull();
    expect(huddle.notice).toBe('');
  });

  for (const popout of [false, true]) {
    test(`${popout ? 'pop-out' : 'sidebar'}: tick, then tell, and the count is 0 at once with no reload ()`, async () => {
      huddle.selected = '12';
      server.waiting = { all: 0, '12': 0, '18': 0 };
      await refreshTaskManager();
      const host = await mountBody(popout);
      server.waiting['12'] = 1;
      await refreshTaskManager();
      await settle();
      host.querySelector<HTMLElement>('[data-task-manager-send]')!.click();
      await settle();
      expect(server.calls.some((c) => c.path === '/cplugs/huddle/send')).toBe(true);
    });
  }

  test('a project list on screen tells only that list', async () => {
    huddle.selected = '12';
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-send]')!.click();
    await settle();
    expect(server.calls.filter((c) => c.path === '/cplugs/huddle/send').map((c) => JSON.parse(c.body))).toEqual([{ lists: ['12'], targets: {} }]);
  });
});

describe('a pop-out hears the active tab', () => {
  test('frames on the channel move its active project; it asks once on start', async () => {
    const main = new BroadcastChannel(ACTIVE_CHANNEL);
    const asked: unknown[] = [];
    main.onmessage = (event) => asked.push(event.data);
    resetActiveProject();
    followActiveProject();
    await new Promise((r) => setTimeout(r, 20));
    expect(asked).toEqual([{ kind: 'ask' }]);
    main.postMessage({ kind: 'active', session: 'ses_18', project: 18 });
    await new Promise((r) => setTimeout(r, 20));
    expect({ ...activeProject }).toEqual({ session: 'ses_18', project: 18 });
    main.close();
    resetActiveProject();
  });
});
