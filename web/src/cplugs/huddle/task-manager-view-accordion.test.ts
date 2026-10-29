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
import { taskManagerPrefs, refreshPrefs, viewFrom } from './task-manager-prefs.svelte';
import { FOLDS_KEY, projectFoldKey, resetAccordion, setSectionFolded, statusFolds } from './task-manager-status-folds.svelte';
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
  resetAccordion();
  try { localStorage.removeItem(FOLDS_KEY); } catch {  }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  taskManagerPrefs.accordion = false;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const isOpen = (host: HTMLElement, list: string): boolean => host.querySelector(`[data-task-manager-status-list="${list}"]`) !== null;
const key = (host: HTMLElement): HTMLElement => host.querySelector<HTMLElement>('[data-task-manager-accordion-key]')!;

describe('carnivore\'s view is removed', () => {
  test('no claude view key is drawn', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-view-key="claude"]')).toBeNull();
    expect(host.querySelector('[data-task-manager-view-key="status"]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-view-key="area"]')).not.toBeNull();
  });

  test('a stored claude view reads as by group and is stored back as area', async () => {
    expect(viewFrom({ view: 'claude' })).toBe('area');
    expect(viewFrom({ view: 'bogus' })).toBe('status');
    server.prefs = { revision: 3, settings: { view: 'claude' } };
    await refreshPrefs();
    await settle();
    expect(taskManagerPrefs.view).toBe('area');
    expect(server.prefs.settings.view).toBe('area');
  });
});

describe('the accordion', () => {
  test('the key is an icon key with a tooltip and aria-pressed, off by default', async () => {
    const host = await mountBody();
    expect(key(host).getAttribute('aria-pressed')).toBe('false');
    expect(key(host).getAttribute('title')).toBeTruthy();
    expect(key(host).getAttribute('aria-label')).toBeTruthy();
  });

  test('turning it on keeps the topmost open project and folds the rest; the toggle persists', async () => {
    const host = await mountBody();
    expect(isOpen(host, '12') && isOpen(host, '18')).toBe(true);
    key(host).click();
    await settle();
    expect(server.prefs.settings.accordion).toBe(true);
    expect(key(host).getAttribute('aria-pressed')).toBe('true');
    expect(isOpen(host, 'all')).toBe(true);
    expect(isOpen(host, '12')).toBe(false);
    expect(isOpen(host, '18')).toBe(false);
    expect(localStorage.getItem(FOLDS_KEY)).toBeNull();
  });

  test('opening a folded project folds the others; the open one cannot be closed', async () => {
    server.prefs = { revision: 3, settings: { accordion: true } };
    await refreshPrefs();
    const host = await mountBody();
    expect(isOpen(host, 'all')).toBe(true);
    expect(isOpen(host, '18')).toBe(false);
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="18"]')!.click();
    await settle();
    expect(isOpen(host, '18')).toBe(true);
    expect(isOpen(host, 'all')).toBe(false);
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="18"]')!.click();
    await settle();
    expect(isOpen(host, '18')).toBe(true);
  });

  test('the normal project folds survive an accordion round trip (#1482)', async () => {
    setSectionFolded(projectFoldKey('18'), true);
    const stored = localStorage.getItem(FOLDS_KEY);
    const host = await mountBody();
    key(host).click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(isOpen(host, '12')).toBe(true);
    expect(isOpen(host, 'all')).toBe(false);
    expect(localStorage.getItem(FOLDS_KEY)).toBe(stored);
    key(host).click();
    await settle();
    expect(isOpen(host, 'all')).toBe(true);
    expect(isOpen(host, '12')).toBe(true);
    expect(isOpen(host, '18')).toBe(false);
    expect(localStorage.getItem(FOLDS_KEY)).toBe(stored);
  });

  test('off, every project may be open at once', async () => {
    const host = await mountBody();
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-fold="12"]')!.click();
    await settle();
    expect(isOpen(host, '12') && isOpen(host, '18')).toBe(true);
  });
});
