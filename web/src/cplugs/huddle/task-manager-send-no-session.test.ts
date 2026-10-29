/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const ELSEWHERE = [{ id: 'ses_c', label: 'Agent - Carnivore (Carnivore)', elsewhere: true }, { id: 'ses_h', label: 'Hockey (Fantasy Hockey 2026)', elsewhere: true }];
const server = vi.hoisted(() => ({ calls: [] as { path: string; body: string }[], waiting: 1, started: false }));

const item = (id: number, list: string, status: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `${list} item ${id}`, note: '', position: id, created_by: 'joe', kind: '', state: 'open', number: 1, revision: 1,
  created_seq: id, seq: id, deleted: false, thread: [], unread: false, status, section: status, group: null, ...extra,
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      server.calls.push({ path, body: String(init.body ?? '') });
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 0, open: 0, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '81', name: 'Trader', project_id: 81, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0,
            untold: server.waiting > 0, waiting_to_send: server.waiting }] };
      }
      if (path === '/cplugs/huddle/lists/81/sessions') {
        if (server.started) return { list: '81', sessions: [{ id: 'ses_new', label: 'Trader', activity_status: 'idle' }], default: 'ses_new', reason: 'only_session' };
        return { list: '81', sessions: ELSEWHERE, default: null, reason: 'pick' };
      }
      if (path === '/projects') return [{ id: 81, name: 'Trader', path: '/p/trader', default_launch_profile: 'claude' }];
      if (path === '/sessions' && init.method === 'POST') {
        server.started = true;
        return { id: 'ses_new' };
      }
      if (path === '/cplugs/huddle/send') {
        const body = JSON.parse(String(init.body)) as { lists: string[]; targets: Record<string, string> };
        if (!body.targets['81']) return { results: [{ list: '81', status: 'no_session', sessions: ELSEWHERE }] };
        server.waiting = 0;
        return { results: [{ list: '81', status: 'sent', target: body.targets['81'], label: 'Agent - Carnivore (Carnivore)' }] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') {
        return { cursor: 3, groups: [{ list: '81', name: 'Trader', project_id: 81, revision: 2, groups: [], items: [
          item(1, '81', 'waiting_to_send'),
          item(2, '81', 'question', { created_by: 'claude', thread: [{ id: 9, item_id: 2, author: 'claude', kind: 'question', text: 'which feed?', answered: false, created_at: 0, seq: 2 }] }),
        ] }] };
      }
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { refreshPrefs } from './task-manager-prefs.svelte';
import { AGGREGATE } from './huddle-model';
import { resetSendPicks, sendPicks } from './huddle-send-many.svelte';
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

beforeEach(async () => {
  server.calls = [];
  server.waiting = 1;
  server.started = false;
  huddle.selected = AGGREGATE;
  resetSendPicks();
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  test('a tell covering a project with no session opens the pop-up with a picker, and the pick sends it there', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout } });
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-send]')!.click();
    await settle();
    const ask = host.querySelector<HTMLElement>('[data-task-manager-send-ask-list="81"]');
    expect(ask).not.toBeNull();
    expect(ask!.querySelector('.hdtl-ask-name')!.textContent).toBe('Trader');
    expect([...ask!.querySelectorAll('.hdtl-ask-item')].map((li) => li.textContent)).toEqual(['81 item 1']);
    const pick = host.querySelector<HTMLSelectElement>('[data-task-manager-send-ask-pick="81"]')!;
    expect(pick).not.toBeNull();
    expect([...pick.options].map((o) => o.value)).toEqual(['', 'start:new', 'ses_c', 'ses_h', 'start:stop']);
    expect(host.querySelector('[data-task-manager-send-ask-none="81"]')).toBeNull();
    pick.value = 'ses_c';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-send-send]')!.click();
    await settle();
    const tells = server.calls.filter((c) => c.path === '/cplugs/huddle/send').map((c) => JSON.parse(c.body));
    expect(tells.at(-1)).toEqual({ lists: ['81'], targets: { '81': 'ses_c' } });
    expect(sendPicks.asking).toBeNull();
    expect(host.querySelector('[data-huddle-reply-target]')).toBeNull();
  });

  async function askAndPick(host: HTMLElement, value: string): Promise<void> {
    host.querySelector<HTMLElement>('[data-task-manager-send]')!.click();
    await settle();
    const pick = host.querySelector<HTMLSelectElement>('[data-task-manager-send-ask-pick="81"]')!;
    pick.value = value;
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-send-send]')!.click();
    await settle();
  }

  test('nothing is delivered until Joe picks: the first press pastes nowhere, and stop sends nothing', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout } });
    await settle();
    await askAndPick(host, 'start:stop');
    const tells = server.calls.filter((c) => c.path === '/cplugs/huddle/send').map((c) => JSON.parse(c.body));
    expect(tells).toEqual([{ lists: ['81'], targets: {} }]);
    expect(server.calls.some((c) => c.path === '/sessions')).toBe(false);
    expect(server.waiting).toBe(1);
    expect(sendPicks.picks['81']).toBeUndefined();
    expect(huddle.notice).toContain('still waiting to send');
  });

  test('start a new session creates one in the project folder and tells THAT session once it is at its prompt', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(HuddleBody, { target: host, props: { popout } });
    await settle();
    await askAndPick(host, 'start:new');
    for (let i = 0; i < 5; i += 1) await settle();
    const create = server.calls.find((c) => c.path === '/sessions');
    expect(JSON.parse(create!.body)).toMatchObject({ working_dir: '/p/trader', project_name: 'Trader', agent_type: 'claude', auto_start_claude: true });
    const tells = server.calls.filter((c) => c.path === '/cplugs/huddle/send').map((c) => JSON.parse(c.body));
    expect(tells.at(-1)).toEqual({ lists: ['81'], targets: { '81': 'ses_new' } });
    expect(tells.every((b) => !Object.values(b.targets).some((t) => t === 'ses_c' || t === 'ses_h'))).toBe(true);
    expect(server.waiting).toBe(0);
  });
});
