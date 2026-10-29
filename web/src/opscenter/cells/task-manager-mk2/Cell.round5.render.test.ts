/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { metaFor } from '../../engine/meta';

const msg = (id: number, item: number, author: string, kind: string, text: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: item, author, kind, text, answered: false, created_at: id, seq: id, ...extra });
const mk = (id: number, extra: Record<string, unknown>) => ({
  id, list: '7', text: `task ${id}`, title: `task ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], status: 'working', section: 'working', ...extra,
});
const ITEMS = () => [
  mk(21, { needs_you: true, needs_action: 'read', unread: true, info_unread: 1, info_unseen: true, thread: [msg(5, 21, 'claude', 'info', 'the build is green and ready', { unread: true })] }),
  mk(22, { thread: [1, 2, 3, 4, 5, 6].map((n) => msg(30 + n, 22, n % 2 ? 'claude' : 'joe', 'reply', `message number ${n}`, { unread: false })) }),
  mk(23, { status: 'scheduled', section: 'scheduled', state: 'open', start_trigger: { kind: 'at', fire_at: 1893020620, fire_at_iso: '2030-01-26T09:17:00-04:00' } }),
];

const wire = vi.hoisted(() => ({ writes: [] as string[], open: [] as Array<() => void> }));
vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: (path: string, init: RequestInit = {}) => {
      if (init.method === 'POST') { wire.writes.push(path); return new Promise((resolve) => { wire.open.push(() => resolve({})); }); }
      if (path === '/swarm/roster') return Promise.resolve({ agents: [] });
      if (path === '/cplugs/huddle') return Promise.resolve({ revision: 1, settings: { view: 'status', hideCompleted: false } });
      if (path === '/cplugs/huddle/focus') return Promise.resolve({ focus: null });
      if (path === '/cplugs/huddle/lists') return Promise.resolve({ cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 1 }] });
      if (path.startsWith('/cplugs/huddle/aggregate')) return Promise.resolve({ cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: ITEMS() }] });
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return Promise.resolve({ list: one[1], revision: 1, cursor: 0, groups: [], items: ITEMS() });
      return Promise.resolve({});
    },
  };
});
vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  sessions: { data: [{ session_row_id: 1, project_id: 7, session: { id: 'ses_1', working_dir: '/x' } }] },
}));
vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Mark2 from './Cell.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { findItem, huddle, markRead } from '../../../cplugs/huddle/huddle.svelte';
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';
import { BASE_FIELDS_HOST } from '../../../cplugs/huddle/task-manager-base-field';

cplugEnablement.enabled = { huddle: true };
const apps: Array<ReturnType<typeof mount>> = [];
afterEach(() => {
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
  wire.writes.length = 0;
  for (const release of wire.open.splice(0)) release();
  try { localStorage.clear(); } catch {  }
});

async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function draw(state: 'compact' | 'opened' | 'detailed' = 'opened'): Promise<HTMLElement> {
  localStorage.setItem('carnivore.core.task-manager-mk2.tm.task-state', JSON.stringify(state));
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  apps.push(mount(Mark2, { target: host, props: { width: 380, height: 600, meta: metaFor('task-manager'), instance: 'tm', scope } }));
  await settle();
  return host;
}

const sectionOfRow = (host: HTMLElement, id: number): string | null =>
  host.querySelector(`[data-huddle-item="${id}"]`)?.closest('[data-task-manager-status-section]')?.getAttribute('data-task-manager-status-section') ?? null;

describe('the action tab holds the current actionable message (point 6)', () => {
  test('an unread info sits first in the action tab and its task is in "needs you"', async () => {
    const host = await draw();
    expect(sectionOfRow(host, 21)).toBe('needs_you');
    const card = host.querySelector('[data-huddle-item="21"] [data-task-manager-mk2-tab="action"] [data-mk2-actionable]') as HTMLElement;
    expect(card, 'the action tab shows no actionable message').not.toBeNull();
    expect(card.textContent).toContain('the build is green and ready');
  });

  test('no "read only" action word in the row or the action tab', async () => {
    const host = await draw();
    const row = host.querySelector('[data-huddle-item="21"]') as HTMLElement;
    expect(row.querySelector('[data-task-manager-action]')).toBeNull();
    expect(row.querySelector('.tkm-asking')).toBeNull();
    expect([...row.querySelectorAll('.mk2-rows dt')].map((el) => el.textContent)).not.toContain('needs');
  });

  test('a scheduled task shows its time and a base edit button that opens the schedule editor', async () => {
    const host = await draw();
    const row = host.querySelector('[data-huddle-item="23"]') as HTMLElement;
    expect(row.querySelector('[data-task-manager-due]')).not.toBeNull();
    const key = row.querySelector('[data-task-manager-schedule-edit-row="23"]') as HTMLElement;
    expect(key.getAttribute('data-btn')).not.toBeNull();
    key.click();
    await settle();
    expect(document.querySelector('[data-task-manager-schedule-editor]')).not.toBeNull();
  });

  test('a task with nothing waiting on the owner shows no actionable block', async () => {
    const host = await draw();
    expect(host.querySelector('[data-huddle-item="22"] [data-mk2-actionable]')).toBeNull();
  });

  test('MARK READ files the task back under its own section at once, with the write still unanswered', async () => {
    const host = await draw();
    void markRead(findItem(21)!);
    await settle();
    expect(wire.writes).toContain('/cplugs/huddle/items/21/seen');
    expect(sectionOfRow(host, 21)).toBe('working');
    expect(host.querySelector('[data-huddle-item="21"] [data-mk2-actionable]')).toBeNull();
  });
});

describe('opened and detailed differ in how much of each tab shows (point 1)', () => {
  const chatOf = (host: HTMLElement): HTMLElement => host.querySelector('[data-huddle-item="22"] .tn-chat') as HTMLElement;
  const showDiscussion = async (host: HTMLElement): Promise<void> => {
    (host.querySelector('[data-huddle-item="22"] [role="tab"][id$="-tab-discussion"]') as HTMLButtonElement).click();
    await settle();
  };

  test('OPENED shows the recent messages in a capped box with the earlier toggle', async () => {
    const host = await draw('opened');
    await showDiscussion(host);
    expect(host.querySelectorAll('[data-huddle-item="22"] .tn-message').length).toBe(3);
    expect(host.querySelector('[data-huddle-item="22"] [data-task-manager-earlier]')).not.toBeNull();
    expect(chatOf(host).classList.contains('tn-chat--all')).toBe(false);
  });

  test('DETAILED is the same scroll box with its show read key, only taller (never the whole thread inline)', async () => {
    const host = await draw('detailed');
    await showDiscussion(host);
    expect(host.querySelectorAll('[data-huddle-item="22"] .tn-message').length).toBe(3);
    const toggle = host.querySelector('[data-huddle-item="22"] [data-task-manager-earlier]') as HTMLElement;
    expect(toggle.textContent?.trim()).toBe('show read (3)');
    expect(chatOf(host).classList.contains('tn-chat--tall')).toBe(true);
    const css = readFileSync(resolve(process.cwd(), 'src/opscenter/cells/task-manager-mk2/mk2-design.css'), 'utf8');
    expect(css).toMatch(/\.tn-chat--tall\s*\{\s*max-height: 560px/);
    expect(css).not.toMatch(/\.tn-chat--all/);
    toggle.click();
    await settle();
    expect(host.querySelectorAll('[data-huddle-item="22"] .tn-message').length).toBe(6);
    expect((host.querySelector('[data-huddle-item="22"] [data-task-manager-earlier]') as HTMLElement).textContent?.trim()).toBe('hide read');
  });
});

describe('one text box (point 3)', () => {
  const textBoxes = (root: ParentNode): HTMLElement[] => [...root.querySelectorAll<HTMLElement>('input, textarea')].filter((el) => !(el instanceof HTMLInputElement) || !['checkbox', 'radio', 'hidden', 'button', 'submit', 'range', 'color', 'file'].includes(el.type));

  test('every text box Mark II draws is the base field: the search, the reply box and the add box, single and multi line', async () => {
    const host = await draw();
    (host.querySelector('[data-task-manager-multiline]') as HTMLButtonElement | null)?.click();
    await settle();
    const boxes = textBoxes(host);
    expect(boxes.length, 'no text box drawn at all').toBeGreaterThanOrEqual(3);
    for (const box of boxes) {
      expect(box.hasAttribute('data-field'), `${box.tagName} ${box.className} is not the base field`).toBe(true);
      expect(box.classList.contains('oc-field'), `${box.className} still wears the legacy field class`).toBe(false);
    }
    expect(host.querySelector('[data-task-manager-search]')?.hasAttribute('data-field')).toBe(true);
    expect(host.querySelector('[data-huddle-reply]')?.hasAttribute('data-field')).toBe(true);
    expect(host.querySelector('[data-task-manager-add]')?.hasAttribute('data-field')).toBe(true);
  });

  test('the note editor on an opened task is the base field too', async () => {
    const host = await draw();
    (host.querySelector('[data-task-manager-note-open="22"]') as HTMLButtonElement).click();
    await settle();
    const note = host.querySelector('[data-task-manager-note-input="22"]') as HTMLElement;
    expect(note.hasAttribute('data-field')).toBe(true);
    expect(note.classList.contains('oc-field')).toBe(false);
  });

  test('the frame asks for base fields, and the reply box is one inline frame (the sidebar search look) inside the panel', async () => {
    const host = await draw();
    expect(host.querySelector('[data-mk2-frame]')?.hasAttribute(BASE_FIELDS_HOST)).toBe(true);
    const form = host.querySelector('[data-huddle-item="22"] .mk2-reply form') as HTMLElement;
    expect(form.classList.contains('oc-inline-field')).toBe(true);
    expect(form.classList.contains('oc-focus-host')).toBe(true);
    expect(form.querySelector('textarea.oc-inline-field__input')?.getAttribute('rows')).toBe('1');
    expect(form.querySelector('button.oc-inline-field__key')).not.toBeNull();
  });

  test('SOURCE: no text box in a component Mark II draws is left on the legacy class without the base action', () => {
    const roots = ['src/cplugs/huddle', 'src/opscenter/cells/task-manager-mk2'];
    const skip = /\/(swarm|chat|agents|style-guide|fixtures)\//;
    const files: string[] = [];
    const walk = (dir: string): void => {
      for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = resolve(dir, entry.name);
        if (entry.isDirectory()) { if (!skip.test(`${path}/`)) walk(path); } else if (path.endsWith('.svelte')) files.push(path);
      }
    };
    for (const root of roots) walk(resolve(process.cwd(), root));
    const offenders: string[] = [];
    for (const file of files) {
      for (const tag of readFileSync(file, 'utf8').match(/<(?:input|textarea)\b[^>]*>/g) ?? []) {
        if (/type="(?:checkbox|radio|hidden|range)"/.test(tag)) continue;
        if (!/use:baseField|data-field/.test(tag)) offenders.push(`${file.replace(process.cwd(), '')}: ${tag.slice(0, 90)}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
