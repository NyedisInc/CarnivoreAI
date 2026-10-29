/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const ASK = {
  item: 1, message: 11, typed: true, answered: false, answer_message_id: null,
  ask: { context: 'one rule', questions: [{ id: 'pick', type: 'single', prompt: 'Which one?', required: true, other: false, options: [{ id: 'a', label: 'option a' }, { id: 'b', label: 'option b' }] }] },
};
const FORM = [{ id: 'pick', type: 'single', prompt: 'Which one?', required: true, options: [{ id: 'a', label: 'option a' }, { id: 'b', label: 'option b' }] },
  { id: 'two', type: 'single', prompt: 'And this?', required: true, options: [{ id: 'x', label: 'x' }, { id: 'y', label: 'y' }] }];

function mk(id: number, status: string, text: string, post: { author?: string; kind?: string; form?: unknown } = {}): unknown {
  return {
    id, list: '1', text, note: '', position: id, created_by: 'claude', state: status === 'review' ? 'review' : 'open', kind: status === 'question' ? 'question' : '',
    revision: 1, created_seq: id, seq: id, deleted: false, status, title: null,
    thread: [{ id: 10 + id, item_id: id, author: post.author ?? 'claude', kind: post.kind ?? 'reply', text: `latest on ${id}`, answered: false, created_at: 1_000 + id, seq: id, ...(post.form ? { form: post.form } : {}) }],
  };
}

const ITEMS = [
  mk(1, 'question', 'pick a thing', { kind: 'question', form: FORM }),
  mk(2, 'review', 'review the thing'),
  mk(3, 'working', 'working one'),
  mk(4, 'working', 'working two'),
  mk(5, 'waiting', 'waiting one'),
  mk(6, 'scheduled', 'scheduled one'),
  mk(7, 'open', 'open one'),
  mk(8, 'open', 'open two'),
];
ITEMS[0] = { ...(ITEMS[0] as object), thread: [{ id: 11, item_id: 1, author: 'claude', kind: 'question', text: 'pick a thing', answered: false, created_at: 1_001, seq: 1, form: FORM, context: 'one rule' }] };

const calls = vi.hoisted(() => [] as { path: string; method?: string; body?: unknown }[]);

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init?: { method?: string; body?: string }) => {
      calls.push({ path, method: init?.method, body: init?.body ? JSON.parse(init.body) : undefined });
      if (path === '/cplugs/huddle/questions/11') return ASK;
      if (path === '/cplugs/huddle/aggregate?live_only=1') return { cursor: 8, groups: [{ list: '1', name: 'p', project_id: 1, revision: 1, items: ITEMS }] };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [{ key: '1', name: 'p', project_id: 1, items: 8, open: 8, review: 1, questions: 1, claude_seq: 8 }] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false } };
      if (path === '/cplugs/huddle/focus') return { focus: null, ok: true };
      if (path === '/swarm/roster') return { agents: [] };
      return {};
    },
  };
});
vi.mock('../../../lib/listing-push/boot', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../../lib/listing-push/boot')>()),
  whenListingPushBooted: (fn: () => void) => fn(),
}));

import Cell from './Cell.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import CellWithHost from '../../shell/fixtures/CellWithHost.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import './meta';
import { setLocale } from '../../../lib/i18n/index.svelte';
import { cplugEnablement } from '../../../cplugs/host/enablement.svelte';
import { metaFor } from '../../engine/meta';
import { sidebarTabs } from '../../../lib/dynamic-tabs/tab-store.svelte';

setLocale('en');
cplugEnablement.enabled = { huddle: true };

let app: ReturnType<typeof mount> | null = null;
const written: [string, unknown][] = [];

/** Let the reads, the store and the effects settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function draw(options: Record<string, boolean | number | string> = {}): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(Cell, { target: host, props: { width: 380, height: 600, meta: metaFor('task-list'), instance: 'hl', options, onOption: (k: string, v: unknown) => written.push([k, v]) } });
  await settle();
  return host;
}

async function drawHosted(options: Record<string, boolean | number | string> = {}): Promise<{ host: HTMLElement; actions: () => ReturnType<typeof declaredActionsFor> }> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(CellWithHost, { target: host, props: { slot: 'task-list', cell: Cell, hostId: 'probe-host', options, onOption: (k: string, v: unknown) => written.push([k, v as never]) } });
  await settle();
  return { host, actions: () => declaredActionsFor('probe-host') };
}

const rowIds = (host: HTMLElement): number[] => [...host.querySelectorAll<HTMLElement>('[data-task-manager-list-row]')].map((el) => Number(el.dataset['taskManagerListRow']));
const press = async (el: Element | null): Promise<void> => {
  el!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  await settle();
};

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  calls.length = 0;
  written.length = 0;
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the rows', () => {
  test('are flat, one per item, questions then reviews then working then waiting then scheduled then open', async () => {
    const host = await draw();
    expect(rowIds(host)).toEqual([1, 2, 4, 3, 5, 6, 8, 7]);
    expect(host.querySelectorAll('[data-task-manager-list-row] [data-task-manager-list-row]')).toHaveLength(0);
    expect([...host.querySelectorAll<HTMLElement>('[data-task-manager-list-row]')].map((el) => el.dataset['status'])).toEqual(['question', 'review', 'working', 'working', 'waiting', 'scheduled', 'open', 'open']);
  });

  test('the ticks filter the rows: an unticked status is gone and the rest stay', async () => {
    const host = await draw({ st_open: false, st_scheduled: false, st_working: false });
    expect(rowIds(host)).toEqual([1, 2, 5]);
  });

  test('nothing ticked reads as one quiet line', async () => {
    const host = await draw(Object.fromEntries(['question', 'review', 'working', 'waiting', 'scheduled', 'open'].map((s) => [`st_${s}`, false])));
    expect(rowIds(host)).toEqual([]);
    expect(host.querySelector('[data-task-manager-list-empty]')?.textContent).toBe('nothing in the ticked statuses.');
  });

  test('the registry count is the rows the copy lists', async () => {
    await draw();
    const { listCount } = await import('./state.svelte');
    expect(listCount()).toBe(8);
    expect(listCount({ st_open: false })).toBe(6);
    expect(listCount({ st_question: false, st_review: false, st_working: false, st_waiting: false, st_scheduled: false, st_open: false })).toBe(0);
  });
});

describe('compact and two-line', () => {
  test('compact is one line a row, two-line adds the latest post under the title with its author', async () => {
    const compact = await draw();
    expect(compact.querySelector('[data-huddle-list-line2]')).toBeNull();
    expect(compact.querySelector('.hl-sum--full')).toBeNull();
    expect(compact.querySelector('[data-task-manager-list-cell]')?.getAttribute('data-density')).toBe('compact');
    unmount(app!);
    document.body.innerHTML = '';
    const full = await draw({ density: 'full' });
    expect(full.querySelectorAll('[data-huddle-list-line2]')).toHaveLength(8);
    expect(full.querySelectorAll('.hl-sum--full')).toHaveLength(8);
    const second = full.querySelector('[data-task-manager-list-row="2"] [data-huddle-list-line2]')!;
    expect(second.textContent).toContain('claude');
    expect(second.textContent).toContain('latest on 2');
    expect(full.querySelector('[data-task-manager-list-row="1"] .hl-who')).toBeNull();
  });

  test('density is a radio set of the widget menu (one line, two lines), the current one checked; picking one writes it through the host', async () => {
    const { host, actions } = await drawHosted();
    expect(host.querySelector('[data-huddle-list-corner], [data-huddle-list-density]'), 'no hover keys over the list').toBeNull();
    const density = actions().filter((a) => a.id.startsWith('density:'));
    expect(density.map((a) => [a.id, a.label, a.checked])).toEqual([['density:compact', 'one line', true], ['density:full', 'two lines', false]]);
    density[1]!.run();
    expect(written).toEqual([['density', 'full']]);
  });
});

describe('opening a row', () => {
  test('one row is open at a time: opening another closes the first, pressing the open row closes it', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-row="3"] .hl-sum'));
    expect(host.querySelectorAll('[data-task-manager-list-open]')).toHaveLength(1);
    expect(host.querySelector('[data-task-manager-list-row="3"] [data-task-manager-list-open]')).not.toBeNull();
    await press(host.querySelector('[data-task-manager-list-row="7"] .hl-sum'));
    expect(host.querySelectorAll('[data-task-manager-list-open]')).toHaveLength(1);
    expect(host.querySelector('[data-task-manager-list-row="7"] [data-task-manager-list-open]')).not.toBeNull();
    expect(host.querySelector('[data-task-manager-list-row="3"] .hl-sum')?.getAttribute('aria-expanded')).toBe('false');
    await press(host.querySelector('[data-task-manager-list-row="7"] .hl-sum'));
    expect(host.querySelectorAll('[data-task-manager-list-open]')).toHaveLength(0);
  });

  test('a question row shows the Task Manager\'s real answer form, no second form', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-row="1"] .hl-sum'));
    const form = host.querySelector('[data-task-manager-list-row="1"] [data-ask-form="11"]');
    expect(form).not.toBeNull();
    expect(form?.getAttribute('data-ask-mode')).toBe('cell');
    expect(calls.some((c) => c.path === '/cplugs/huddle/questions/11')).toBe(true);
    expect(form?.textContent).toContain('Which one?');
  });

  test('another row shows its latest line and "open in task manager", which points the Task Manager at the item', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-row="3"] .hl-sum'));
    expect(host.querySelector('[data-task-manager-list-row="3"] [data-ask-form]')).toBeNull();
    expect(host.querySelector('[data-task-manager-list-words]')?.textContent).toContain('latest on 3');
    const button = host.querySelector<HTMLElement>('[data-task-manager-list-open-tm]')!;
    expect(button.getAttribute('aria-label')).toBe('open in task manager');
    expect(button.getAttribute('title')).toBe('open in task manager');
    expect(button.textContent?.trim()).toBe('');
    const widget = document.createElement('div');
    widget.setAttribute('data-task-manager-all-cell', '');
    document.body.appendChild(widget);
    await press(button);
    const focus = calls.find((c) => c.path === '/cplugs/huddle/focus' && c.method === 'POST');
    expect(focus?.body).toEqual({ list: '1', items: [3], open: 3 });
    expect(document.querySelector('[data-task-manager-list-warn]')).toBeNull();
    expect(sidebarTabs.active()).not.toBe('huddle');
  });

  test('with no Task Manager widget placed anywhere the press warns, writes nothing and does not open the Swarm tab', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-row="3"] .hl-sum'));
    await press(host.querySelector('[data-task-manager-list-open-tm]'));
    const warn = document.querySelector('[data-task-manager-list-warn]');
    expect(warn?.textContent).toContain('no task manager widget is on screen. add one from edit layout.');
    expect(warn?.classList.contains('popup-focus')).toBe(true);
    expect(calls.some((c) => c.path === '/cplugs/huddle/focus' && c.method === 'POST')).toBe(false);
    expect(sidebarTabs.active()).not.toBe('huddle');
    await press(document.querySelector('[data-task-manager-list-warn-ok]'));
    expect(document.querySelector('[data-task-manager-list-warn]')).toBeNull();
  });

  test('a review row has the reply box', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-row="2"] .hl-sum'));
    expect(host.querySelector('[data-task-manager-list-row="2"] textarea, [data-task-manager-list-row="2"] [contenteditable], [data-task-manager-list-row="2"] input')).not.toBeNull();
  });
});

describe('grouping', () => {
  const heads = (host: HTMLElement): string[] => [...host.querySelectorAll<HTMLElement>('[data-task-manager-list-head]')].map((el) => el.textContent!.replace(/\s+/g, ' ').trim());

  test('by status is the default: a header per status with its count, rows under it in the same order', async () => {
    const host = await draw();
    expect(host.querySelector('[data-task-manager-list-cell]')).not.toBeNull();
    expect(heads(host)).toEqual(['questions 1', 'review 1', 'working 2', 'waiting 1', 'scheduled 1', 'open 2']);
    expect(rowIds(host)).toEqual([1, 2, 4, 3, 5, 6, 8, 7]);
  });

  test('by project: a header per project named as the Task Manager names it, with its count', async () => {
    const host = await draw({ group: 'project' });
    expect(heads(host)).toEqual(['p 8']);
    expect(host.querySelector('[data-task-manager-list-head]')?.getAttribute('data-group')).toBe('project');
  });

  test('grouping is the other radio set (status, project): the current one checked; picking one writes it through the host', async () => {
    const { actions } = await drawHosted();
    const group = actions().filter((a) => a.id.startsWith('group:'));
    expect(group.map((a) => [a.id, a.checked])).toEqual([['group:status', true], ['group:project', false]]);
    group[1]!.run();
    expect(written).toEqual([['group', 'project']]);
  });

  test('an unticked status leaves no header and the counts follow the ticks', async () => {
    const host = await draw({ st_open: false, st_working: false });
    expect(heads(host)).toEqual(['questions 1', 'review 1', 'waiting 1', 'scheduled 1']);
  });
});

describe('hover shows the full text of anything cut by an ellipsis', () => {
  function clip(el: HTMLElement): void {
    Object.defineProperty(el, 'scrollWidth', { value: 300, configurable: true });
    Object.defineProperty(el, 'clientWidth', { value: 100, configurable: true });
  }

  test('a clipped title and a clipped second line carry data-tooltip with the whole text once the pointer arrives; a short one does not', async () => {
    const host = await draw({ density: 'full' });
    const title = host.querySelector<HTMLElement>('[data-task-manager-list-row="2"] .hl-title')!;
    const last = host.querySelector<HTMLElement>('[data-task-manager-list-row="2"] [data-huddle-list-line2] > span:last-child')!;
    const short = host.querySelector<HTMLElement>('[data-task-manager-list-row="3"] .hl-title')!;
    clip(title);
    clip(last);
    for (const el of [title, last, short]) el.dispatchEvent(new Event('pointerover', { bubbles: true }));
    expect(title.getAttribute('data-tooltip')).toBe('review the thing');
    expect(last.getAttribute('data-tooltip')).toBe('latest on 2');
    expect(short.getAttribute('data-tooltip')).toBeNull();
    expect(host.querySelector('[data-task-manager-list-row="2"] .hl-sum')?.getAttribute('title')).toBeNull();
  });
});

describe('a host that stores no options', () => {
  test('a home grid cell (no onOption) declares no group or density items and draws no keys, since a choice that stores nothing does nothing', async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(CellInFrame, { target: host, props: { slot: 'task-list', cell: Cell } });
    await settle();
    expect(host.querySelector('[data-task-manager-list-row]')).not.toBeNull();
    expect(host.querySelector('[data-huddle-list-grouping]')).toBeNull();
    expect(host.querySelector('[data-huddle-list-density]')).toBeNull();
    expect(declaredActionsFor('task-list')).toEqual([]);
  });
});

describe('the approve key on a review row (#1797)', () => {
  test('only a review row carries it, as an icon key with a label and title, and it is the owner\'s own tick through the Task Manager route', async () => {
    const host = await draw();
    const keys = [...host.querySelectorAll<HTMLButtonElement>('[data-task-manager-list-approve]')];
    expect(keys.map((k) => k.dataset['taskManagerListApprove'])).toEqual(['2']);
    const key = keys[0]!;
    expect(key.getAttribute('aria-label')).toBe('approve');
    expect(key.getAttribute('title')).toBe('approve');
    expect(key.textContent?.trim()).toBe('');
    expect(key.querySelector('svg[data-icon="approve"]')).not.toBeNull();
    expect(key.closest('[data-task-manager-list-row]')?.getAttribute('data-status')).toBe('review');
    await press(key);
    await vi.waitFor(() => expect(calls.some((c) => c.path === '/cplugs/huddle/items/2' && c.method === 'PATCH' && (c.body as { approved?: boolean }).approved === true)).toBe(true));
  });

  test('pressing the key does not open the row', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-approve]'));
    expect(host.querySelector('[data-task-manager-list-row="2"] [data-task-manager-list-open]')).toBeNull();
  });
});

describe('icon keys instead of big text buttons (#1797)', () => {
  test('an opened row has no .modal-btn text button: open in task manager and the reply send are icon keys with a label and title', async () => {
    const host = await draw();
    await press(host.querySelector('[data-task-manager-list-row="2"] .hl-sum'));
    const open = host.querySelector<HTMLElement>('[data-task-manager-list-row="2"] [data-task-manager-list-open-tm]')!;
    expect(open.classList.contains('oc-ibtn')).toBe(true);
    expect(open.querySelector('svg[data-icon="external"]')).not.toBeNull();
    const send = host.querySelector<HTMLElement>('[data-task-manager-list-row="2"] .hdt-send')!;
    expect(send.classList.contains('oc-ibtn')).toBe(true);
    expect(send.getAttribute('aria-label')).toBe('reply');
    expect(send.getAttribute('title')).toBe('reply');
    expect(send.querySelector('svg[data-icon="send"]')).not.toBeNull();
    expect(host.querySelectorAll('[data-task-manager-list-row="2"] .modal-btn, [data-task-manager-list-row="2"] .oc-btn')).toHaveLength(0);
    const comment = host.querySelector<HTMLElement>('[data-task-manager-list-row="2"] [data-task-manager-comment]')!;
    expect(comment.classList.contains('oc-ibtn')).toBe(true);
    expect(comment.getAttribute('aria-label')).toBe('comment');
    expect(comment.querySelector('svg[data-icon="chat"]')).not.toBeNull();
  });
});
