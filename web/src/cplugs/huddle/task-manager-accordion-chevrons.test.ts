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
}));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if (path === '/cplugs/huddle' && init.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        server.prefs = { revision: server.prefs.revision + 1, settings: { ...server.prefs.settings, ...body.settings } };
        return structuredClone(server.prefs);
      }
      if (path === '/cplugs/huddle') return structuredClone(server.prefs);
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
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
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
  Element.prototype.scrollTo = vi.fn();
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS();
  statusFolds.choices = {};
  try { localStorage.removeItem(FOLDS_KEY); } catch {  }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  resetAccordion();
  taskManagerPrefs.accordion = false;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});


const sectionKeyOf = sectionFoldKey('all', 'review');
const keyBtn = (host: HTMLElement): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-accordion-key]')!;
const secFold = (host: HTMLElement): HTMLElement | null => host.querySelector('[data-task-manager-status-list="all"] button[data-task-manager-status-fold="review"]');
const rows = (host: HTMLElement): number => host.querySelectorAll('[data-task-manager-status-list="all"] [data-task-manager-status-section="review"] > *').length;
const openBlocks = (host: HTMLElement): number => host.querySelectorAll('[data-task-manager-block]').length;
const projectChevrons = (host: HTMLElement): number => host.querySelectorAll('[data-task-manager-project-fold]').length;

describe('accordion view: project chevrons and section folds', () => {
  test('project bars draw no chevron in the accordion, and come back with it off', async () => {
    const host = await mountBody();
    expect(projectChevrons(host)).toBe(3);
    keyBtn(host).click();
    await settle();
    expect(projectChevrons(host)).toBe(0);
    expect(host.querySelector('[data-task-manager-level="project"] [data-icon^="chevron"]')).toBeNull();
    keyBtn(host).click();
    await settle();
    expect(projectChevrons(host)).toBe(3);
  });

  test('section chevrons render and fold normally, writing the stored section folds', async () => {
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    expect(secFold(host)).not.toBeNull();
    expect(rows(host)).toBe(1);
    secFold(host)!.click();
    await settle();
    expect(rows(host)).toBe(0);
    expect(statusFolds.choices[sectionKeyOf]).toBe(true);
    secFold(host)!.click();
    await settle();
    expect(rows(host)).toBe(1);
  });

  test('exactly one project stays open, and the open one cannot be closed', async () => {
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    expect(openBlocks(host)).toBe(1);
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(openBlocks(host)).toBe(1);
    expect(host.querySelector('[data-task-manager-status-list="12"]')).not.toBeNull();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(host.querySelector('[data-task-manager-status-list="12"]')).not.toBeNull();
  });

  test('accordion off restores the prior project folds exactly', async () => {
    setSectionFolded(projectFoldKey('18'), true);
    const stored = localStorage.getItem(FOLDS_KEY);
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(localStorage.getItem(FOLDS_KEY)).toBe(stored);
    keyBtn(host).click();
    await settle();
    expect(host.querySelector('[data-task-manager-status-list="all"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-status-list="12"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-status-list="18"]')).toBeNull();
  });
});
