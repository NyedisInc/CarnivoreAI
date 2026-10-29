/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { metaFor } from '../../engine/meta';

const mk = (id: number, list: string, extra: Record<string, unknown> = {}) => ({
  id, list, text: `item ${id}`, note: '', position: id, created_by: 'joe', state: 'open', kind: 'task',
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], ...extra,
});
const msg = (id: number, author: 'joe' | 'claude', text: string) => ({ id, item_id: 5, author, kind: 'reply', text, answered: false, created_at: 1_700_000_000 + id, seq: id });
/** Item 5 carries a thread (the last agent message is new), a note, a tag and a fork parent. */
let asReview = false;
const REVIEW = { state: 'review', review_description: 'check the tab strip at phone width', review_where: 'task manager II', review_action: 'tick' };
const OPEN = (list: string) => mk(5, list, {
  ...(asReview ? REVIEW : {}),
  from_inbox: { id: 9, text: 'raw words from the add box' }, title: 'ship the tabs', text: 'ship the tabs now', note: 'check phone width', unread: true, tagged_by: 'cv-ui', tagged_session_key: 'u-cv-ui', forked_from: 2,
  thread: [msg(1, 'claude', 'first reply, spec at https://example.com/spec'), msg(2, 'joe', 'my answer'), msg(3, 'claude', 'second reply')], thread_count: 3,
});

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/roster') return { agents: [] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { view: 'area', hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '7', name: 'Carnivore', project_id: 7, items: 2, open: 2, review: 0, questions: 0, claude_seq: 0, unread: 1 }] };
      if (path.startsWith('/cplugs/huddle/aggregate')) return { cursor: 0, groups: [{ list: '7', name: 'Carnivore', project_id: 7, revision: 1, groups: [], items: [mk(1, '7'), OPEN('7')] }] };
      const one = /^\/cplugs\/huddle\/lists\/(\d+)(?:\?.*)?$/.exec(path);
      if (one) return { list: one[1], revision: 1, cursor: 0, groups: [], items: [mk(1, one[1] as string), OPEN(one[1] as string)] };
      return {};
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

import Original from '../task-manager/Cell.svelte';
import Mark2 from './Cell.svelte';
import Mk2Host from './fixtures/Mk2Host.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { clearViewFilter } from '../../../cplugs/huddle/task-manager-view-filter.svelte';
import { huddle } from '../../../cplugs/huddle/huddle.svelte';
import { resetInspections } from '../../../cplugs/huddle/task-manager-design/inspection.svelte';
import { actionDataOf } from './mk2-task-tabs';
import { applyProgress } from '../../../cplugs/huddle/task-manager-progress.svelte';
import Mk2TaskTabs from './Mk2TaskTabs.svelte';
import type { HuddleItem } from '../../../cplugs/huddle/huddle-model';

cplugEnablement.enabled = { huddle: true };
/** A file under `cells/`, from the web root vitest runs in. Inputs: relative path. Output: absolute path. */
const CELLS = (rel: string): string => resolve(process.cwd(), 'src/opscenter/cells', rel);
const apps: Array<ReturnType<typeof mount>> = [];

afterEach(() => {
  asReview = false;
  for (const app of apps.splice(0)) unmount(app);
  document.body.innerHTML = '';
  clearViewFilter();
  resetInspections();
  huddle.openId = null as never;
  try { localStorage.clear(); } catch { /* jsdom without storage: the widget keeps an in-memory value */ }
});

/** Settle the mocked reads. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

/** Mount a cell on project 7, inside a frame header when `hostId` is given. Output: the host element after it settled. */
async function draw(cell: typeof Original, hostId?: string): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  const scope = { sessionId: 'ses_1', rowId: 1, workingDir: '/x', projectId: 7 };
  const props = { width: 380, height: 600, meta: metaFor('task-manager'), instance: 'tm', scope };
  apps.push(hostId ? mount(Mk2Host, { target: host, props: { cell, hostId, props } }) : mount(cell, { target: host, props }));
  await settle();
  return host;
}

/** Open task 5 by its row's toggle. Inputs: host. Output: the detail element. */
async function open(host: HTMLElement): Promise<HTMLElement> {
  if (!host.querySelector('[data-task-manager-detail="5"]')) {
    (host.querySelector('[data-task-manager-toggle="5"]') as HTMLButtonElement).click();
    await settle();
  }
  return host.querySelector('[data-task-manager-detail="5"]') as HTMLElement;
}

describe('TM Mark II side color switches', () => {
  test('project colors and status bar are menu switches, on by default, and each flips its frame attribute', async () => {
    const host = await draw(Mark2, 'mk2-side');
    const actions = () => declaredActionsFor('mk2-side');
    const frame = host.querySelector('[data-mk2-frame]') as HTMLElement;
    expect(actions().filter((a) => ['project-colors', 'status-bar'].includes(a.id)).map((a) => [a.id, a.label, a.checked])).toEqual([['project-colors', 'project colors', true], ['status-bar', 'status bar', true]]);
    expect([frame.dataset.mk2ProjectColors, frame.dataset.mk2StatusBar]).toEqual(['on', 'on']);
    actions().find((a) => a.id === 'project-colors')!.run();
    flushSync();
    expect([frame.dataset.mk2ProjectColors, frame.dataset.mk2StatusBar]).toEqual(['off', 'on']);
    expect(actions().find((a) => a.id === 'project-colors')!.checked).toBe(false);
    actions().find((a) => a.id === 'status-bar')!.run();
    flushSync();
    expect([frame.dataset.mk2ProjectColors, frame.dataset.mk2StatusBar]).toEqual(['off', 'off']);
  });

  test('the frame CSS removes exactly the project bars and the status stripe, only under its own attributes', () => {
    const css = readFileSync(CELLS('task-manager-mk2/Mk2Frame.svelte'), 'utf8');
    expect(css).toMatch(/data-mk2-project-colors='off'\][^{]*\.hd-block[^{]*::before\s*\{\s*background: none/);
    expect(css).toMatch(/data-mk2-project-colors='off'\][^{]*hd-pname[^{]*\{\s*color: var\(--oc-text-secondary\)/);
    expect(css).toMatch(/data-mk2-status-bar='off'\][^{]*\.tkm-state\)\s*\{\s*display: none/);
  });
});

describe('TM Mark II task tabs', () => {
  test('an opened task shows the strip directly under its title and the reply box under it; the old conversation box is gone', async () => {
    const detail = await open(await draw(Mark2));
    const tabs = detail.querySelector('[data-task-manager-mk2-tabs="5"]') as HTMLElement;
    expect(tabs).not.toBeNull();
    expect(detail.firstElementChild).toBe(tabs);
    expect([...tabs.querySelectorAll('[role="tab"]')].map((el) => el.querySelector('.oc-ptab__label')?.textContent?.trim())).toEqual(['action', 'unread (1)', 'details', 'subtasks']);
    expect(detail.querySelector('[data-task-manager-thread-box]')).toBeNull();
    const panel = tabs.querySelector('.tn-tabbody') as HTMLElement;
    const reply = panel.querySelector('.mk2-reply [data-huddle-reply="5"]') as HTMLElement;
    expect(reply).not.toBeNull();
    expect(panel.lastElementChild).toBe(reply.closest('.mk2-reply'));
    expect(detail.closest('[data-huddle-item="5"]')!.querySelector('[data-task-part="reply"]')).toBeNull();
  });

  test('no @agent button under the tabs', async () => {
    expect((await open(await draw(Mark2))).querySelector('[data-task-manager-tagged]')).toBeNull();
  });

  test('the original task manager keeps its @agent button and its conversation box', async () => {
    const original = await open(await draw(Original));
    expect(original.querySelector('[data-task-manager-tagged]')).not.toBeNull();
    expect(original.querySelector('[data-task-manager-thread-box]')).not.toBeNull();
  });

  test('the review block and its action are inside the action tab, never above the strip', async () => {
    asReview = true;
    const host = await draw(Mark2);
    const detail = await open(host);
    const row = host.querySelector('[data-huddle-item="5"]') as HTMLElement;
    const card = row.querySelector('.tkm-review') as HTMLElement;
    expect(card).not.toBeNull();
    expect(card.closest('[data-task-manager-mk2-tab="action"]')).not.toBeNull();
    expect(card.parentElement?.classList.contains('hdr')).toBe(false);
    expect(row.querySelectorAll('.tkm-review').length).toBe(1);
    ((detail.querySelector('[role="tab"][id$="-tab-details"]')) as HTMLButtonElement).click();
    await settle();
    expect(row.querySelector('.tkm-review')).toBeNull();
  });

  test('each tab shows its data, the discussion and details tabs as the new Task Manager draws them', async () => {
    const detail = await open(await draw(Mark2));
    const tabs = detail.querySelector('[data-task-manager-mk2-tabs="5"]') as HTMLElement;
    const body = () => tabs.querySelector('[data-task-manager-mk2-tab]') as HTMLElement;
    const pick = async (id: string) => { (tabs.querySelector(`[role="tab"][id$="-tab-${id}"]`) as HTMLButtonElement).click(); await settle(); };
    const classes = (el: Element | null) => [...(el?.children ?? [])].map((child) => child.className.trim()).filter((name) => !name.startsWith('mk2-reply'));
    expect(body().dataset.taskManagerMk2Tab).toBe('action');
    expect(body().querySelector('[data-mk2-status]')).toBeNull();

    await pick('discussion');
    expect(classes(body())).toEqual(['tn-history-toggle', 'tn-chat']);
    const chat = body().querySelector('.tn-chat') as HTMLElement;
    expect(chat.getAttribute('role')).toBe('region');
    expect(classes(chat)).toEqual(['tn-newline', 'tn-message new']);
    expect(chat.querySelector('.tn-newline')?.textContent).toBe('new messages');
    const message = chat.querySelector('.tn-message') as HTMLElement;
    expect(message.dataset.messageIndex).toBe('2');
    expect(classes(message)).toEqual(['tn-message-top', 'tn-md']);
    expect(message.querySelector('.tn-message-top strong')?.textContent).toBe('cv-ui');
    expect(message.querySelector('.tn-message-top .tn-subtle')?.textContent).toBe('carnivore \u00b7 agent');
    expect(message.querySelector('.tm-new-mark')?.textContent).toBe('new');
    expect(message.querySelector('.tn-md')?.textContent).toContain('second reply');
    expect(body().querySelector('.tn-history-toggle')?.textContent?.trim()).toBe('show read (2)');
    expect(body().querySelector('.tn-history-toggle')?.getAttribute('data-btn')).not.toBeNull();
    (body().querySelector('[data-task-manager-earlier]') as HTMLButtonElement).click();
    await settle();
    expect([...body().querySelectorAll('.tn-message')].map((el) => el.className.trim())).toEqual(['tn-message', 'tn-message owner', 'tn-message new']);
    expect(body().querySelector('.tn-history-toggle')?.textContent?.trim()).toBe('hide read');
    expect(body().querySelector('.tn-message.owner strong')?.textContent).toBe('you');

    await pick('details');
    const details = body().querySelector('.tm-details') as HTMLElement;
    expect(classes(details)).toEqual(['tn-overline', 'tn-md', '', 'tn-overline', 'tn-md', 'tn-overline', 'tn-md', 'tn-line between', 'tm-shared-list']);
    expect(details.querySelector('.tn-overline')?.textContent).toBe('task');
    expect([...details.querySelectorAll('dl > dt')].map((el) => el.textContent)).toEqual(['project', 'agent', 'parent']);
    expect([...details.querySelectorAll('dl > dd')].map((el) => el.textContent)).toEqual(['Carnivore', 'cv-ui', 'task 2']);
    expect(details.querySelector('.tn-md')?.textContent).toBe('ship the tabs now');
    expect(details.querySelectorAll('.tn-overline')[1]?.textContent).toBe('your note');
    expect(details.querySelectorAll('.tn-md')[1]?.textContent).toContain('check phone width');
    expect(details.querySelector('.tn-line.between')?.textContent).toContain('shared in this task');
    expect(details.querySelector('.tn-line.between')?.textContent).toContain('1 items');
    expect(details.querySelectorAll('.tm-shared-item').length).toBe(1);
    expect(details.querySelector('.tm-shared-open small')?.textContent).toContain('link');
    (details.querySelector('.tm-shared-open') as HTMLButtonElement).click();
    await settle();
    expect(body().querySelector('.tm-resource-viewer')).not.toBeNull();
    (body().querySelector('.tm-resource-viewer > .tn-chip') as HTMLButtonElement).click();
    await settle();
    expect(body().querySelector('.tm-details')).not.toBeNull();
  });

  test('the github issue shows in the details tab only, never as a row of the action tab', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    const url = 'https://github.com/Example-owner/CarnivoreAIDev/issues/1710';
    const item = { ...OPEN('7'), github_issue: url, review: { link: url } } as unknown as HuddleItem;
    apps.push(mount(Mk2TaskTabs, { target, props: { item } }));
    await settle();
    expect(target.querySelector('[data-task-manager-mk2-tab="action"]')?.textContent).not.toContain('issues/1710');
    expect(target.querySelector('[data-mk2-issue]')).toBeNull();
    (target.querySelector('[role="tab"][id$="-tab-details"]') as HTMLButtonElement).click();
    await settle();
    const link = target.querySelector('[data-mk2-issue]') as HTMLAnchorElement;
    expect(link.getAttribute('href')).toBe(url);
    expect(link.textContent).toContain('Example-owner/CarnivoreAIDev #1710');
    expect(link.className).toBe('tn-resource');
    expect(link.closest('.tm-details')).not.toBeNull();
  });

  test('the original task manager draws no tab strip on the same open task', async () => {
    const detail = await open(await draw(Original));
    expect(detail).not.toBeNull();
    expect(detail.querySelector('[data-task-manager-mk2-tabs]')).toBeNull();
  });

  test('an unread task wears its new count in the discussion tab badge, as the new Task Manager words it', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(Mk2TaskTabs, { target, props: { item: OPEN('7') as unknown as HuddleItem } }));
    await settle();
    expect([...target.querySelectorAll('[role="tab"]')].map((el) => el.querySelector('.oc-ptab__label')?.textContent?.trim())).toEqual(['action', 'unread (1)', 'details', 'subtasks']);
    expect(target.querySelector('[data-tab="discussion"] .oc-ptab__badge')).toBeNull();
    expect(target.querySelector('[data-tab="discussion"] .oc-ptab__dot')).not.toBeNull();
    expect([...target.querySelectorAll('[role="tab"]')].map((el) => el.getAttribute('aria-label'))).toEqual(['action', 'unread (1)', 'details', 'subtasks']);
    expect(target.querySelectorAll('[role="tab"] .oc-ptab__icon svg').length).toBe(4);
    expect(target.querySelector('.oc-ptabs')?.classList.contains('oc-ptabs--compact')).toBe(true);
    expect(target.querySelector('.tn-detail > .oc-ptabs + .tn-tabbody')).not.toBeNull();
  });

  test('the tab strip is the shared base one: no restyled copy, mark read at its right end, and no CSS here reaches a tab or a base button', async () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    apps.push(mount(Mk2TaskTabs, { target, props: { item: OPEN('7') as unknown as HuddleItem } }));
    await settle();
    expect(target.querySelector('.tn-tabs')).toBeNull();
    expect(target.querySelector('.oc-ptabs > .oc-ptabs__trailing [data-task-manager-mark-read="5"]')).not.toBeNull();
    const sheet = readFileSync(CELLS('task-manager-mk2/mk2-design.css'), 'utf8');
    expect(sheet).not.toMatch(/\.tn-tabs|\.oc-ptab\b[^)]*\{/);
    for (const rule of sheet.split('\n').filter((line) => /\.mk2-design button/.test(line) && !/aria-pressed/.test(line))) expect(rule).toMatch(/:not\(\.oc-ptab, \[data-btn\]/);
  });

  test('the action tab data is pure and reads only the item', () => {
    const item = { ...OPEN('7'), needs_action: 'pick one' } as unknown as HuddleItem;
    expect(actionDataOf(item)).toMatchObject({ statusKey: null, rows: [{ value: 'pick one' }] });
  });
});

describe('TM Mark II round 10: no boxed note sits between the tabs and the panel', () => {
  test('worker lines are the action tab status as plain text, the add box label is gone and its words live in details', async () => {
    applyProgress({ progress: { '5': [{ worker: 'main', phase: 'running', note: 'running round 9d: check by eye', age_s: 60, stale: false }] } });
    const detail = await open(await draw(Mark2));
    expect(detail.querySelector('[data-task-manager-progress]')).toBeNull();
    expect(detail.querySelector('[data-task-manager-from-inbox]')).toBeNull();
    expect(detail.querySelector('[data-task-manager-note]')).toBeNull();
    const status = detail.querySelector('[data-mk2-status]') as HTMLElement;
    expect(status.textContent).toContain('running: running round 9d: check by eye');
    expect(status.textContent).not.toContain('claude has read it');
    (detail.querySelector('[role="tab"][id$="-tab-details"]') as HTMLButtonElement).click();
    await settle();
    expect(detail.querySelector('[data-mk2-add-box-words]')?.textContent).toContain('raw words from the add box');
    applyProgress({ progress: {} });
  });

  test('a status with no words of its own draws no status row, and a wait draws no chip below the strip', () => {
    const open5 = { ...OPEN('7'), status: 'working' } as unknown as HuddleItem;
    expect(actionDataOf(open5).statusKey).toBeNull();
    expect(actionDataOf({ ...open5, status: 'waiting' } as unknown as HuddleItem).statusKey).toBe('cplug.huddle.status.waiting');
  });
});

describe('TM Mark II row icons are the left drawer rows icons', () => {
  const drawnStroke = (svg: Element): number => Number(svg.getAttribute('stroke-width')) * Number(svg.getAttribute('width')) / 24;
  const rowIcons = (host: HTMLElement): Element[] => [...host.querySelectorAll('[data-huddle-item] svg[data-icon]')].filter((svg) => svg.getAttribute('stroke') === 'currentColor' && !svg.closest('[data-task-part]'));

  test('THE CAUSE: the compact row draws odd 11px icons with a stroke thinner than a pixel', async () => {
    const icons = rowIcons(await draw(Original));
    expect(icons.length).toBeGreaterThan(2);
    expect(icons.some((svg) => Number(svg.getAttribute('width')) % 2 === 1)).toBe(true);
    expect(icons.some((svg) => drawnStroke(svg) < 1)).toBe(true);
  });

  test('THE FIX: every Mark II row icon is a whole even pixel size at stroke 2, as the drawer rows draw, with no stroke override over the shared icon', async () => {
    const icons = rowIcons(await draw(Mark2));
    expect(icons.length).toBeGreaterThan(2);
    for (const svg of icons) {
      expect([12, 14]).toContain(Number(svg.getAttribute('width')));
      expect(svg.getAttribute('stroke-width')).toBe('2');
    }
    const frame = readFileSync(CELLS('task-manager-mk2/Mk2Frame.svelte'), 'utf8');
    expect(frame).not.toMatch(/non-scaling-stroke|svg\[data-icon\]/);
    expect(readFileSync(resolve(process.cwd(), 'src/opscenter/ui/Icon.svelte'), 'utf8')).not.toMatch(/non-scaling-stroke/);
  });
});
