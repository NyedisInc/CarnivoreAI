/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const mk = (id: number, list: string, section: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
});

const server = vi.hoisted(() => ({
  prefs: { revision: 3, settings: {} as Record<string, unknown> },
  groups: [] as unknown[],
  held: [] as Array<() => void>,
  hold: false,
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle' && init.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        const answer = structuredClone(server.prefs);
        if (server.hold) await new Promise<void>((release) => server.held.push(release));
        return answer;
      }
      if (path === '/cplugs/huddle') {
        const answer = structuredClone(server.prefs);
        if (server.hold) await new Promise<void>((release) => server.held.push(release));
        return answer;
      }
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') {
        return { cursor: 0, lists: [
          { key: 'all', name: null, project_id: null, items: 1, open: 1, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '12', name: 'alpha', project_id: 12, items: 6, open: 6, review: 0, questions: 0, claude_seq: 0, unread: 0 },
          { key: '18', name: 'beta', project_id: 18, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 0 },
        ] };
      }
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 9, groups: structuredClone(server.groups) };
      if (/\/sessions$/.test(path)) return { sessions: [], default: null, reason: 'pick' };
      return {};
    },
  };
});

import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs, setAccordion } from './task-manager-prefs.svelte';
import { FOLDS_KEY, projectFoldKey, resetAccordion, sectionFoldKey, setSectionFolded, statusFolds } from './task-manager-status-folds.svelte';
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
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout: false } });
  await settle();
  return host;
}

const GROUPS = () => [
  { list: 'all', name: null, project_id: null, revision: 3, groups: [], items: [mk(1, 'all', 'review')] },
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [mk(11, '12', 'review')] },
  { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'review')] },
];

beforeEach(async () => {
  Element.prototype.scrollTo = vi.fn(); // jsdom has no scrollTo; a bar click scrolls its project
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS();
  statusFolds.choices = {};
  try { localStorage.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable */ }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  resetAccordion();
  server.hold = false;
  server.held = [];
  taskManagerPrefs.accordion = false;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});


const keyBtn = (host: HTMLElement): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-accordion-key]')!;
const projectChevrons = (host: HTMLElement): number => host.querySelectorAll('[data-task-manager-project-fold]').length;

describe('accordion setting writes', () => {
  test('on, off, and the project chevrons are drawn again, also after a reload', async () => {
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    expect(projectChevrons(host)).toBe(0);
    keyBtn(host).click();
    await settle();
    expect(keyBtn(host).getAttribute('aria-pressed')).toBe('false');
    expect(projectChevrons(host)).toBe(3);
    expect(host.querySelectorAll('[data-task-manager-level="project"] [data-task-manager-project-fold] svg').length).toBe(3);
    await refreshPrefs();
    await settle();
    expect(projectChevrons(host)).toBe(3);
  });

  test('a read that started before the press and answers after it does not undo the press', async () => {
    const host = await mountBody();
    server.hold = true;
    const read = refreshPrefs();
    const write = setAccordion(true);
    await settle();
    server.held.splice(0).forEach((release) => release());
    await Promise.all([read, write]);
    await settle();
    expect(taskManagerPrefs.accordion).toBe(true);
    expect(projectChevrons(host)).toBe(0);
  });

  test('two quick presses end where the second left them, whatever order the answers arrive in', async () => {
    const host = await mountBody();
    server.hold = true;
    const first = setAccordion(true);
    await settle();
    const second = setAccordion(false);
    await settle();
    const releases = server.held.splice(0);
    releases.reverse().forEach((release) => release());
    await Promise.all([first, second]);
    await settle();
    expect(taskManagerPrefs.accordion).toBe(false);
    expect(keyBtn(host).getAttribute('aria-pressed')).toBe('false');
    expect(projectChevrons(host)).toBe(3);
  });
});
