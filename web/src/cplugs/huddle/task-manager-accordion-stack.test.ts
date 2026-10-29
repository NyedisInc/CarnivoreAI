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

import { readFileSync } from 'node:fs';
import { huddle, refreshTaskManager } from './huddle.svelte';
import { taskManagerPrefs, refreshPrefs } from './task-manager-prefs.svelte';
import { FOLDS_KEY, projectFoldKey, resetAccordion, sectionFoldKey, setSectionFolded, statusFolds } from './task-manager-status-folds.svelte';
import { AGGREGATE } from './huddle-model';
import { accordionStackFits } from './task-manager-sticky';
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
const bar = (host: HTMLElement, list: string): HTMLElement => host.querySelector<HTMLElement>(`[data-task-manager-project-scroll="${list}"]`)!.closest('h2')!;

describe('accordion view: the stack', () => {
  test('bars before the open project stack at the top, bars after it at the bottom, the open body scrolls', async () => {
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(bar(host, 'all').classList.contains('hd-stack-top')).toBe(true);
    expect(bar(host, '12').classList.contains('hd-stack-open')).toBe(true);
    expect(bar(host, '18').classList.contains('hd-stack-bottom')).toBe(true);
    expect(host.querySelector('[data-task-manager-scroll]')!.getAttribute('data-task-manager-accordion-stack')).toBe('on');
    const body = host.querySelector('[data-task-manager-open-body]')!;
    expect(body.classList.contains('hd-block--open')).toBe(true);
    expect(body.getAttribute('data-task-manager-block')).toBe('12');
  });

  test('normal view carries no stack class', async () => {
    const host = await mountBody();
    expect(host.querySelector('.hd-stack-top, .hd-stack-open, .hd-stack-bottom, .hd-block--open, [data-task-manager-accordion-stack]')).toBeNull();
  });

  test('the fit rule keeps a third of the box for the open project', () => {
    expect(accordionStackFits(600, 5, 30)).toBe(true);
    expect(accordionStackFits(300, 8, 30)).toBe(false);
    expect(accordionStackFits(0, 50, 30)).toBe(true);
  });

  test('the stack bars neutralise the sticky top and bottom offsets', () => {
    const css = readFileSync('src/cplugs/huddle/TaskManagerProjectHead.svelte', 'utf8');
    const rule = css.match(/\.hd-stack-top,\s*\.hd-stack-open,\s*\.hd-stack-bottom\s*\{([^}]*)\}/)![1];
    expect(rule).toMatch(/position:\s*relative/);
    expect(rule).toMatch(/top:\s*auto/);
    expect(rule).toMatch(/bottom:\s*auto/);
  });

  test('the topmost bar docked at the bottom follows the open body and carries its own top hairline', async () => {
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(bar(host, '18').previousElementSibling).toBe(host.querySelector('.hd-block--open'));
    const css = readFileSync('src/cplugs/huddle/HuddleBody.svelte', 'utf8');
    const rule = css.match(/\.hd-block \+ :global\(h2\)\s*\{([^}]*)\}/)![1];
    expect(rule).toMatch(/inset 0 1px 0 var\(--oc-line-rule\)/);
    expect(rule).toMatch(/inset 0 -1px 0 var\(--oc-line-rule\)/);
  });

  test('stacking resets the scroll box to the top, and so does changing the open project', async () => {
    const host = await mountBody();
    const box = host.querySelector<HTMLElement>('[data-task-manager-scroll]')!;
    box.scrollTop = 150;
    keyBtn(host).click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="12"]')!.click();
    await settle();
    expect(box.getAttribute('data-task-manager-accordion-stack')).toBe('on');
    expect(box.scrollTop).toBe(0);
    box.scrollTop = 40;
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="18"]')!.click();
    await settle();
    expect(box.scrollTop).toBe(0);
  });

  test('the top stack sits flush: no stack bar carries a sticky offset, and sticky bars outside the stack still do', async () => {
    const host = await mountBody();
    keyBtn(host).click();
    await settle();
    host.querySelector<HTMLElement>('[data-task-manager-project-scroll="18"]')!.click();
    await settle();
    for (const list of ['all', '12', '18']) {
      const style = bar(host, list).getAttribute('style') ?? '';
      expect(style).not.toMatch(/--_top|--_bottom/);
    }
    expect(bar(host, 'all').classList.contains('hd-stack-top')).toBe(true);
    expect(bar(host, '12').classList.contains('hd-stack-top')).toBe(true);
    keyBtn(host).click();
    await settle();
    expect(bar(host, '12').getAttribute('style')).toMatch(/--_top: calc\(var\(--hd-phead-h\) \* 1\)/);
  });
});

describe('normal view: the bar after an open project body', () => {
  test('follows the body directly and the same rule gives it a top hairline, one rule for both views', async () => {
    const host = await mountBody();
    expect(host.querySelector('[data-task-manager-accordion-stack]')).toBeNull();
    const body = host.querySelector('[data-task-manager-block="12"]')!;
    expect(bar(host, '18').previousElementSibling).toBe(body);
    expect(body.parentElement!.classList.contains('hd-scroll')).toBe(true);
    const css = readFileSync('src/cplugs/huddle/HuddleBody.svelte', 'utf8');
    const rule = css.match(/\.hd-scroll > \.hd-block \+ :global\(h2\)\s*\{([^}]*)\}/)![1];
    expect(rule).toMatch(/inset 0 1px 0 var\(--oc-line-rule\)/);
    expect(rule).toMatch(/inset 0 -1px 0 var\(--oc-line-rule\)/);
  });
});
