/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const bookmarks = vi.hoisted(() => ({ branchFrom: vi.fn(), rewindTo: vi.fn(), addBookmark: vi.fn() }));
vi.mock('../../../lib/bookmarks/api', async (actual) => ({ ...(await actual<typeof import('../../../lib/bookmarks/api')>()), ...bookmarks }));
const own = vi.hoisted(() => ({ getPeek: vi.fn(), openRestorePoint: vi.fn() }));
vi.mock('./api', () => own);
const opener = vi.hoisted(() => ({ openConversation: vi.fn() }));
vi.mock('../../../lib/conversation-open/open', () => opener);
vi.mock('../../../lib/item-settings/store.svelte', () => ({ widgetSetting: (_id: string, key: string) => ({ showPreview: true, previewTurns: 4 })[key] }));
const feed = vi.hoisted(() => ({ res: { data: null as unknown, status: 'ok' } }));
vi.mock('../../api/session-timeline.svelte', () => ({ sessionTimeline: () => feed.res, releaseSessionTimeline: vi.fn() }));
vi.mock('../../lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1' }));
vi.mock('../../api', async (actual) => ({
  ...(await actual<typeof import('../../api')>()),
  sessions: { data: [{ session: { id: 'ses_1' }, session_row_id: 7, project_id: 4, tmux_session: 'cloude_x', label: 'x', activity_status: 'idle' }] },
}));

import Cell from './Cell.svelte';
import { ApiError } from '../../api/auth.svelte';
import { t } from '../../../lib/i18n/index.svelte';
import CellInFrame from '../../shell/fixtures/CellInFrame.svelte';
import { markOf, timelineFixture } from './fixture';
import { timelineFilters } from './filters.svelte';
import { ALL_FILTERS_ON } from './model';
import { META } from '../../engine/meta';
import { frameFor } from './plot-model';
import type { SessionTimeline } from './types';

let handle: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
  await tick();
  flushSync();
}

async function draw(data: SessionTimeline, box: { width: number; height: number }, extra: Record<string, unknown> = {}): Promise<void> {
  feed.res = { data, status: 'ok' };
  const el = document.createElement('div');
  document.body.append(el);
  handle = mount(Cell, { target: el, props: { ...box, meta: META.timeline, instance: 'timeline', scope: null, phone: false, ...extra } as never });
  await settle();
}

const q = <T extends Element = HTMLElement>(sel: string): T => document.querySelector<T>(sel)!;
const all = (sel: string): HTMLElement[] => [...document.querySelectorAll<HTMLElement>(sel)];

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  timelineFilters.value = { ...ALL_FILTERS_ON };
  bookmarks.branchFrom.mockResolvedValue({ label: 'branch' });
  bookmarks.rewindTo.mockResolvedValue({ resumed_copy: true });
  bookmarks.addBookmark.mockResolvedValue({ id: 9 });
  own.getPeek.mockResolvedValue({ parts: [{ entry_uuid: 'p1', role: 'user', text: 'the words before the compact', timestamp: '', truncated: false }] });
  own.openRestorePoint.mockResolvedValue({ transcript_status: 'written', session: { status: 'started', detail: '' } });
  opener.openConversation.mockResolvedValue('switched');
});

afterEach(() => {
  if (handle) void unmount(handle);
  handle = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
});

const markBtn = (id: string): HTMLElement => q(`[data-key="mark:${id}"]`);
const act = (name: string): HTMLButtonElement | null => document.querySelector<HTMLButtonElement>(`[data-action="${name}"]`);
const WIDE = { width: 2400, height: 1400 };

describe('the bodies by box', () => {
  test('the vertical column for every box and the list on a phone', () => {
    for (const h of [63, 120, 420, 800, null]) expect(frameFor(false, h).body).toBe('column');
    expect(frameFor(true, 900).body).toBe('list');
  });

  test('the cell record keeps the floor at 192 x 96 and one state each way, since the layout never changes with size', () => {
    const meta = META.timeline;
    expect([meta.minPx, meta.minHeight]).toEqual([192, 96]);
    expect(meta.widthStates).toHaveLength(1);
    expect(meta.heightStates).toHaveLength(1);
  });
});

describe('always vertical', () => {
  test.each([[2400, 500], [1152, 289], [700, 420], [300, 120], [320, 800]])('%i x %i draws the vertical column, time running down', async (width, height) => {
    await draw(timelineFixture(), { width, height });
    expect(q('[data-timeline]').dataset.body).toBe('column');
    expect(document.querySelector('[data-timeline-column]')).not.toBeNull();
    expect(document.querySelector('.tlx-plot, .tlx-lane, .tlx-axis')).toBeNull();
    const rails = all('[data-bar]');
    expect(rails.map((r) => r.dataset.bar)).toEqual(['conv-a', 'conv-b', 'conv-c']);
    const tops = rails.map((r) => parseFloat(r.style.top));
    expect(tops).toEqual([...tops].sort((a, c) => a - c));
    expect(rails.every((r) => r.style.left === '' && r.style.width === '' && parseFloat(r.style.height) > 0)).toBe(true);
  });
});

describe('the rail', () => {
  test('one rail per conversation, every mark a named button, one tab stop on the current conversation', async () => {
    await draw(timelineFixture(), WIDE, { scope: { sessionId: 'ses_1', rowId: 7, workingDir: '', projectId: 4 } });
    expect(q('[data-timeline]').dataset.body).toBe('column');
    expect(all('[data-bar]').map((b) => b.dataset.bar)).toEqual(['conv-a', 'conv-b', 'conv-c']);
    expect(all('.tlc-mark').map((m) => m.dataset.kind).sort()).toEqual(['bookmark', 'compact', 'restart', 'restart', 'restore']);
    expect(all('.tlc-mark').every((m) => !!m.getAttribute('aria-label') || m.getAttribute('aria-hidden') === 'true')).toBe(true);
    expect(all('.tlc-sleep')).toHaveLength(2);
    expect(all('[data-hook]').map((h) => h.dataset.hook)).toEqual(['conv-c']);
    expect(all('[data-key][tabindex="0"]').map((b) => b.dataset.key)).toEqual(['conv:conv-c']);
    expect(document.querySelector('[data-facet]')).toBeNull();
  });

  test('a dashboard tile (no scope) follows the focused session and offers a picker', async () => {
    await draw(timelineFixture(), WIDE);
    expect(q('[data-facet="timeline-session"]')).not.toBeNull();
    expect(q('[data-timeline]').dataset.session).toBe('ses_1');
  });
});

describe('the key and the filters', () => {
  test('each toggle hides only its own kind, never moves a rail, and is remembered on this device', async () => {
    await draw(timelineFixture(), WIDE);
    const before = all('[data-bar]').map((b) => b.style.top + b.style.height);
    q('[data-filter="bookmarks"]').click();
    await settle();
    expect(document.querySelector('.tlc-mark[data-kind="bookmark"]')).toBeNull();
    expect(all('.tlc-mark')).toHaveLength(4);
    expect(q('[data-filter="bookmarks"]').getAttribute('aria-pressed')).toBe('false');
    for (const key of ['sleeps', 'restores', 'compacts', 'restarts']) q(`[data-filter="${key}"]`).click();
    await settle();
    expect(all('.tlc-mark')).toHaveLength(0);
    expect(all('.tlc-sleep')).toHaveLength(0);
    expect(all('[data-bar]').map((b) => b.style.top + b.style.height)).toEqual(before);
    expect(JSON.parse(localStorage.getItem('oc.timeline.filters')!)).toMatchObject({ bookmarks: false, sleeps: false, restores: false });
    expect(q('.tlx-main .oc-state__title').textContent).toBe(t('opscenter.cell.timeline.view.none.shown'));
  });
});

describe('in a widget frame', () => {
  test('the kind key goes up into the widget header, not the body', async () => {
    feed.res = { data: timelineFixture(), status: 'ok' };
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    };
    const el = document.createElement('div');
    document.body.append(el);
    handle = mount(CellInFrame, { target: el, props: { slot: 'timeline', cell: Cell } as never });
    await settle();
    expect(document.querySelector('[data-widget-head] [data-timeline-key]')).not.toBeNull();
    expect(document.querySelector('.tlx [data-timeline-key]')).toBeNull();
  });
});

describe('a picked point', () => {
  test('a bookmark branches and rewinds through the existing actions, rewind only after the arm box is ticked', async () => {
    await draw(timelineFixture(), WIDE);
    markBtn('bookmark:1').click();
    await settle();
    expect(markBtn('bookmark:1').getAttribute('aria-pressed')).toBe('true');
    act('branch')!.click();
    await settle();
    expect(bookmarks.branchFrom).toHaveBeenCalledWith(7, { bookmarkId: 1 });
    expect(act('rewind')!.disabled).toBe(true);
    act('rewind')!.click();
    await settle();
    expect(bookmarks.rewindTo).not.toHaveBeenCalled();
    q<HTMLInputElement>('input[data-arm]').click();
    await settle();
    expect(act('rewind')!.disabled).toBe(false);
    act('rewind')!.click();
    await settle();
    expect(bookmarks.rewindTo).toHaveBeenCalledWith(7, { bookmarkId: 1 }, true);
    expect(q<HTMLInputElement>('input[data-arm]').checked).toBe(false);
    expect(act('bookmark')).toBeNull();
  });

  test('a record of the current conversation can be bookmarked and branched by its entry', async () => {
    const data = timelineFixture();
    data.marks.push(markOf({ id: 'compact:conv-c:3', kind: 'compact', conversation_id: 'conv-c', at: '2026-10-10T12:30:00Z', entry_uuid: 'cb2', can_peek: true, pre_tokens: 5000 }));
    await draw(data, WIDE);
    markBtn('compact:conv-c:3').click();
    await settle();
    act('bookmark')!.click();
    await settle();
    expect(bookmarks.addBookmark).toHaveBeenCalledWith(7, 'cb2');
    act('branch')!.click();
    await settle();
    expect(bookmarks.branchFrom).toHaveBeenCalledWith(7, { entryUuid: 'cb2' });
  });

  test('a compact on an earlier conversation can be opened but not branched or rewound', async () => {
    await draw(timelineFixture(), WIDE);
    markBtn('compact:conv-b:9').click();
    await settle();
    expect(act('branch')).toBeNull();
    expect(act('rewind')).toBeNull();
    act('open')!.click();
    await settle();
    expect(opener.openConversation).toHaveBeenCalledWith({ conversationId: 'conv-b', sessionUuid: 'row-uuid-1', projectId: 4 });
  });

  test('a conversation backup offers open a copy only', async () => {
    await draw(timelineFixture(), WIDE);
    markBtn('restore:conv-b:20261010T112500Z-kill').click();
    await settle();
    expect(['branch', 'rewind', 'bookmark'].map((a) => act(a))).toEqual([null, null, null]);
    act('copy')!.click();
    await settle();
    expect(own.openRestorePoint).toHaveBeenCalledWith('conv-b', '20261010T112500Z-kill');
  });

  test('open a copy while the backups plugin is off says so in plain words', async () => {
    own.openRestorePoint.mockRejectedValue(new ApiError('the save plugin is off', 409, null, { detail: { code: 'cplug_disabled', detail: 'the save plugin is off' } }));
    await draw(timelineFixture(), WIDE);
    markBtn('restore:conv-b:20261010T112500Z-kill').click();
    await settle();
    act('copy')!.click();
    await settle();
    const notice = q('.tlx-card__notice');
    expect(notice.textContent).toBe(t('opscenter.cell.timeline.copy.plugin_off'));
    expect(notice.classList.contains('tlx-card__notice--error')).toBe(true);
  });

  test('a second click on the same mark lets go, and Escape clears a pick', async () => {
    await draw(timelineFixture(), WIDE);
    markBtn('bookmark:1').click();
    await settle();
    markBtn('bookmark:1').click();
    await settle();
    expect(act('branch')).toBeNull();
    markBtn('bookmark:1').click();
    await settle();
    q('[data-timeline-rows]').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await settle();
    expect(act('branch')).toBeNull();
  });
});

describe('the peek', () => {
  test('hovering a mark reads nothing; picking it reads the messages around it once, read only', async () => {
    await draw(timelineFixture(), WIDE);
    const mark = markBtn('compact:conv-b:9');
    mark.dispatchEvent(new PointerEvent('pointerenter'));
    await settle();
    expect(own.getPeek).not.toHaveBeenCalled();
    mark.click();
    await settle();
    expect(own.getPeek).toHaveBeenCalledWith(7, 'conv-b', 'cb', 4);
    expect(q('[data-timeline-detail]').textContent).toContain('the words before the compact');
    mark.click();
    mark.click();
    await settle();
    expect(own.getPeek).toHaveBeenCalledTimes(1);
  });

  test('a refused peek says why in the detail and never throws', async () => {
    own.getPeek.mockRejectedValue(new Error('this conversation\'s transcript is not on this computer'));
    await draw(timelineFixture(), WIDE);
    markBtn('compact:conv-b:9').click();
    await settle();
    expect(q('[data-timeline-detail]').textContent).toContain('not on this computer');
  });
});

describe('the phone list', () => {
  test('a vertical list in time order with the same marks, actions and filters', async () => {
    await draw(timelineFixture(), { width: 360, height: 600 }, { phone: true });
    expect(q('[data-timeline]').dataset.body).toBe('list');
    expect(all('[data-timeline-list] > li').map((li) => li.dataset.listBar ?? li.dataset.listMark ?? li.dataset.listGap)).toEqual([
      'conv-a', 'restart:conv-a:1', 'sleep:conv-a:1', 'conv-b', 'compact:conv-b:9', 'restore:conv-b:20261010T112500Z-kill',
      'conv-c', 'bookmark:1', 'restart:conv-c:2', 'sleep:conv-c:2',
    ]);
    q('[data-list-mark="bookmark:1"] button').click();
    await settle();
    q('[data-branch]').click();
    await settle();
    expect(bookmarks.branchFrom).toHaveBeenCalledWith(7, { bookmarkId: 1 });
    q('[data-filter="restarts"]').click();
    await settle();
    expect(document.querySelector('[data-list-mark^="restart"]')).toBeNull();
    expect(document.querySelector('[data-list-bar="conv-a"]')).not.toBeNull();
  });
});

describe('the states', () => {
  async function noteFor(status: string, data: SessionTimeline | null = null): Promise<string> {
    feed.res = { data, status };
    const el = document.createElement('div');
    document.body.append(el);
    handle = mount(Cell, { target: el, props: { width: 300, height: 200, meta: META.timeline, instance: 'timeline', scope: null, phone: false } as never });
    await settle();
    const state = q('[data-widget-note]').dataset.widgetNote!;
    void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
    return state;
  }

  test('no data yet says so, an empty session says so, a failed read says so', async () => {
    expect(await noteFor('loading')).toBe('loading');
    expect(await noteFor('ok', { ...timelineFixture(), bars: [], marks: [], gaps: [] })).toBe('empty');
    expect(await noteFor('error')).toBe('error');
  });
});
