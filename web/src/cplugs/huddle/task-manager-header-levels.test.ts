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
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle') return server.prefs;
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
import { refreshPrefs } from './task-manager-prefs.svelte';
import { FOLDS_KEY, projectFoldKey, sectionFoldKey, statusFolds } from './task-manager-status-folds.svelte';
import { readFileSync } from 'node:fs';
import { taskManagerPrefs } from './task-manager-prefs.svelte';
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

async function mountBody(popout: boolean): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleBody, { target: host, props: { popout } });
  await settle();
  return host;
}

/** alpha: 2 questions, a review with 2 unread looks and 1 unread info, a review with 1 unread info, 1 working. */
const GROUPS = () => [
  { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [], items: [
    mk(11, '12', 'question'), mk(12, '12', 'question'),
    mk(13, '12', 'review', { attention_unread: 2, attention_unseen: true, info_unread: 1, info_unseen: true }),
    mk(14, '12', 'review', { info_unread: 1, info_unseen: true }),
    mk(16, '12', 'working'),
  ] },
  { list: '18', name: 'beta', project_id: 18, revision: 5, groups: [], items: [mk(21, '18', 'review'), mk(22, '18', 'open')] },
];

beforeEach(async () => {
  server.prefs = { revision: 3, settings: { hideCompleted: false } };
  server.groups = GROUPS();
  statusFolds.choices = {};
  try { localStorage.removeItem(FOLDS_KEY); } catch { /* storage may be unavailable */ }
  huddle.selected = AGGREGATE;
  huddle.groups = null;
  huddle.openId = null;
  await refreshPrefs();
  await refreshTaskManager();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});



function rule(file: string, selector: string): Record<string, string> {
  const css = readFileSync(new URL(file, import.meta.url), 'utf8');
  const at = css.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no rule ${selector} in ${file}`);
  const block = css.slice(css.indexOf('{', at) + 1, css.indexOf('}', at));
  return Object.fromEntries(block.split(';').map((d) => d.split(':')).filter((p) => p.length >= 2).map(([k, ...v]) => [k!.trim(), v.join(':').trim()]));
}

function look(file: string, selector: string, shadowRule = selector): string {
  const d = rule(file, selector);
  const shadow = rule(file, shadowRule)['box-shadow'] ?? '';
  return [d['font-size'], d['font-weight'] ?? '400', d['text-transform'] ?? 'none', /inset (2|3)px 0 0/.test(shadow) ? 'bar' : 'nobar'].join('|');
}

test('project, status and area headers each wear a look the others do not, and the project is the largest', () => {
  const project = look('./TaskManagerProjectHead.svelte', '.hd-pfold', '.hd-group');
  const status = look('./TaskManagerStatusSections.svelte', '.hss-fold', '.hss-head');
  const area = look('./TaskManagerSections.svelte', '.hds-fold', '.hds-head');
  expect(new Set([project, status, area]).size).toBe(3);
  expect(project).toContain('var(--oc-fs-body)');
  expect(project).toContain('uppercase');
  expect(status).toContain('uppercase');
  expect(area).toContain('none');
  expect(area).toContain('600');
  expect(rule('./TaskManagerProjectHead.svelte', '.hd-group')['box-shadow']).toContain('var(--_project');
  expect(rule('./TaskManagerSections.svelte', '.hds-head')['box-shadow']).toContain('var(--oc-line-frame)');
});

describe.each([['the sidebar', false], ['the pop-out', true]])('%s', (_name, popout) => {
  const levels = (host: HTMLElement): string[] => [...new Set([...host.querySelectorAll<HTMLElement>('[data-task-manager-level]')].map((e) => e.dataset.taskManagerLevel as string))];

  test('the status view carries project and status levels, and a folded area subheader the sub level', async () => {
    const host = await mountBody(popout);
    expect(levels(host)).toEqual(['project', 'status']);
  });

  test('the area view carries project and area levels', async () => {
    taskManagerPrefs.view = 'area';
    server.groups = [
      { list: '12', name: 'alpha', project_id: 12, revision: 20, groups: [{ id: 5, list: '12', name: 'widgets', position: 0, folded: false }],
        items: [mk(13, '12', 'review', { group: 5 })] },
    ];
    await refreshTaskManager();
    const host = await mountBody(popout);
    expect(levels(host)).toEqual(expect.arrayContaining(['project', 'area', 'sub']));
    taskManagerPrefs.view = 'status';
  });
});
