import { ApiError, authFetch } from '../sdk';
import { resourcePush } from '../sdk';
import { familyOf, LIVENESS } from '../sdk';
import { onEventFrame } from '../sdk/terminal';
import { t } from '../sdk';
import { untrack } from 'svelte';
import { taskManagerUi, markTaskManagerSeen } from './task-manager-ui.svelte';
import {
  AGGREGATE, ALL_LIST, TASK_MANAGER_FAMILY, completedCount, isAgentList, moveId, refusalCode, serverKey, surfaceFor,
  type TaskManagerAddOutcome, type TaskManagerAggregateBody, type TaskManagerGroup, type TaskManagerInboxEntry, type HuddleItem, type TaskManagerRepeat, type TaskManagerListBody, type TaskManagerListRow, type TaskManagerMessage,
} from './huddle-model';
import { followPrefs, prefsSettled, taskManagerPrefs, onHideCompletedChange, onViewChange } from './task-manager-prefs.svelte';
import { boundaryOf } from './task-manager-boundary';
import { needsSeen } from './task-manager-lights';
import { POST_KINDS, postKindOf, unreadCount, type TaskManagerPostKind } from './task-manager-posts';
import { createReadOrder, type TaskManagerReadLane } from './task-manager-read-order';
import { holdRead, overlayHeldReads } from './task-manager-held-read';
import { applyAnswered, applyMarkRead, applyReply, applyReviewCheck, applyTick, mergeThread, type Undo } from './task-manager-optimistic';
import { applyFlushHold } from './task-manager-flush-hold';
import { bindDone, refreshDoneOf, refreshHeldDone, withDone } from './task-manager-done.svelte';
import { itemWhere, outboxPost } from './task-manager-outbox';
import { keptNoticeKey } from '../../lib/outbox/outbox';
import { lockFromPayload, lockReason } from './review-lock';
import { readTaskManagerSnapshot, saveTaskManagerSnapshot } from './task-manager-snapshot';
import { DATA_FRAME, deltaLive, type DeltaMarker } from '../sdk/task-manager-delta';
import { createDeltaLanes } from './task-manager-delta-lanes';

export const POLL_MS = 60_000;
const COALESCE_MS = 200;
const STARTUP_WAIT_MS = 1500;

export const huddle = $state<{
  lists: TaskManagerListRow[];
  selected: string;
  body: TaskManagerListBody | null;
  groups: TaskManagerGroup[] | null;
  addTarget: string;
  status: 'idle' | 'ok' | 'error';
  notice: string;
  viewing: boolean;
  openId: number | null;
}>({ lists: [], selected: AGGREGATE, body: null, groups: null, addTarget: ALL_LIST, status: 'idle', notice: '', viewing: false, openId: null });

let started = false;
let aggregateHolds = 0;
let pending: ReturnType<typeof setTimeout> | null = null;
const queued = { read: false, lists: false };
let reading = false;
let aggregateCovered = false;
let startupWait: ReturnType<typeof setTimeout> | null = null;
const startupGate = { hello: false, prefs: false };
let hideReadWith: boolean | null = null;
const readOrder = createReadOrder();
let writesOut = 0;

function paints(ticket: number, lane: TaskManagerReadLane): boolean {
  if (readOrder.accepts(ticket, lane)) return true;
  if (readOrder.needsReread()) scheduleRefresh();
  return false;
}

export async function trackWrite<T>(run: () => Promise<T>, rereads = false): Promise<T> {
  readOrder.writeStarted();
  writesOut += 1;
  try {
    return await run();
  } finally {
    readOrder.writeSettled();
    writesOut -= 1;
    deltaLanes.settled();
    if (!rereads && readOrder.needsReread()) scheduleRefresh();
    if (writesOut === 0) retryOwedThread();
  }
}

function seg(key: string): string {
  return encodeURIComponent(key);
}

async function paintLists(rows: TaskManagerListRow[]): Promise<void> {
  huddle.lists = applyFlushHold(rows);
  const decision = surfaceFor(huddle.lists, taskManagerUi.seen);
  if (decision.surface) {
    markTaskManagerSeen(decision.newest);
    if (!huddle.viewing && decision.list && huddle.selected !== AGGREGATE && decision.list !== huddle.selected) await selectList(decision.list);
  }
}

export async function refreshLists(): Promise<void> {
  const ticket = readOrder.begin();
  try {
    const body = await authFetch<{ lists: TaskManagerListRow[] } & DeltaMarker>('/cplugs/huddle/lists');
    if (!paints(ticket, 'lists')) return;
    await paintLists(deltaLanes.replay('lists', body) ?? (Array.isArray(body.lists) ? body.lists : []));
  } catch {
    huddle.status = 'error';
  }
}

export function holdAggregate(): () => void {
  aggregateHolds += 1;
  const needs = untrack(() => huddle.groups === null || !pushIsLive() || (aggregateHolds === 1 && huddle.selected !== AGGREGATE));
  if (!aggregateCovered && needs) requestRead(false, true);
  let released = false;
  return () => {
    if (released) return;
    released = true;
    aggregateHolds -= 1;
    if (aggregateHolds === 0 && huddle.selected !== AGGREGATE) huddle.groups = null;
  };
}

const openThread = { id: null as number | null, thread: [] as TaskManagerMessage[] };

function completeOpenThread(groups: TaskManagerGroup[]): TaskManagerGroup[] {
  const id = huddle.openId;
  if (id === null || openThread.id !== id) return groups;
  return groups.map((g) => (g.items.some((i) => i.id === id) ? { ...g, items: completeOpenItems(g.items) } : g));
}

function completeOpenItems(items: HuddleItem[]): HuddleItem[] {
  const id = huddle.openId;
  if (id === null || openThread.id !== id) return items;
  return items.map((i) => (i.id === id ? mergeThread(i, openThread.thread) : i));
}

let threadOwed: number | null = null;

function retryOwedThread(): void {
  const id = threadOwed;
  threadOwed = null;
  if (id !== null) void loadThread(id);
}

export async function loadThread(id: number): Promise<void> {
  const ticket = readOrder.begin();
  try {
    const full = await authFetch<HuddleItem>(`/cplugs/huddle/items/${id}`);
    if (!Array.isArray(full?.thread)) return;
    if (!paints(ticket, 'thread')) {
      threadOwed = id;
      if (writesOut === 0) retryOwedThread();
      return;
    }
    const item = findItem(id);
    if (!item) return;
    openThread.id = id;
    openThread.thread = full.thread;
    item.thread = full.thread;
    item.thread_count = full.thread.length;
    item.thread_slim = false;
  } catch (error) {
    console.warn('huddle: could not read the thread', error);
  }
}

let swarmLaneList: string | null = null;

export function holdSwarmLane(key: string): () => void {
  swarmLaneList = key;
  if (huddle.selected === key) void refreshList();
  return () => {
    if (swarmLaneList !== key) return;
    swarmLaneList = null;
    if (huddle.selected === key) void refreshList();
  };
}

export function readQuery(key: string | null): string {
  hideReadWith = taskManagerPrefs.hideCompleted;
  const params = ['live_only=1', taskManagerPrefs.hideCompleted ? 'hide_completed=1' : '', key !== null && key === swarmLaneList ? 'include_swarm=1' : ''].filter(Boolean);
  return `?${params.join('&')}`;
}

export function doneCount(list: string): number {
  return (huddle.body?.list === list ? huddle.body.done_count : huddle.groups?.find((g) => g.list === list)?.done_count) ?? 0;
}

function repaintDone(list: string, replaced: ReadonlySet<number>): void {
  const swap = (items: HuddleItem[]): HuddleItem[] => withDone(list, items.filter((i) => !replaced.has(i.id)));
  if (huddle.groups) huddle.groups = huddle.groups.map((g) => (g.list === list ? { ...g, items: swap(g.items) } : g));
  if (huddle.body?.list === list) huddle.body = { ...huddle.body, items: swap(huddle.body.items) };
}

bindDone({ extraQuery: (list) => (list === swarmLaneList ? '&include_swarm=1' : ''), repaint: repaintDone });

export async function refreshList(): Promise<void> {
  const key = huddle.selected;
  try {
    if (key === AGGREGATE || aggregateHolds > 0) {
      const ticket = readOrder.begin();
      const all = await authFetch<TaskManagerAggregateBody>(`/cplugs/huddle/aggregate${readQuery(null)}`);
      if (key === AGGREGATE && huddle.selected !== key) return;
      if (!paints(ticket, 'aggregate')) return;
      huddle.groups = completeOpenThread((Array.isArray(all.groups) ? all.groups : []).map((g) => ({ ...g, items: overlayHeldReads(withDone(g.list, g.items)) })));
      deltaLanes.replay('aggregate', all);
      saveTaskManagerSnapshot('aggregate', huddle.groups);
    }
    if (key === AGGREGATE) {
      huddle.body = null;
    } else {
      const ticket = readOrder.begin();
      const body = await authFetch<TaskManagerListBody>(`/cplugs/huddle/lists/${seg(key)}${readQuery(key)}`);
      if (huddle.selected !== key) return;
      if (!paints(ticket, 'body')) return;
      huddle.body = { ...body, items: overlayHeldReads(withDone(body.list, body.items)) };
      deltaLanes.replay('body', body);
      saveTaskManagerSnapshot(key, huddle.body);
      if (aggregateHolds === 0) huddle.groups = null;
    }
    huddle.status = 'ok';
    void refreshHeldDone();
  } catch {
    huddle.status = 'error';
  }
}

export async function refreshTaskManager(): Promise<void> {
  await refreshLists();
  await refreshList();
}

const deltaLanes = createDeltaLanes({
  groups: () => huddle.groups,
  setGroups: (next) => {
    huddle.groups = completeOpenThread(next.map((g) => ({ ...g, items: overlayHeldReads(g.items) })));
    saveTaskManagerSnapshot('aggregate', huddle.groups);
  },
  body: () => huddle.body,
  setBody: (next, previous) => {
    const open = previous.items.find((i) => i.id === huddle.openId && !i.thread_slim);
    if (open) Object.assign(openThread, { id: open.id, thread: open.thread });
    huddle.body = { ...next, items: overlayHeldReads(completeOpenItems(next.items)) };
    saveTaskManagerSnapshot(next.list, huddle.body);
  },
  setLists: (rows) => void paintLists(rows),
  includeSwarm: (list) => list === swarmLaneList,
  refresh: () => scheduleRefresh(),
  writing: () => writesOut > 0,
  doneTouched: (list) => void refreshDoneOf(list),
});

function scheduleRefresh(): void {
  requestRead(true);
}

function requestRead(lists: boolean, now = false): void {
  queued.read = true;
  queued.lists = queued.lists || lists;
  if (now && started && !reading && !startupWait) runReadNow();
  else armRead();
}

function armRead(): void {
  if (pending || reading || startupWait) return;
  pending = setTimeout(() => void runQueuedRead(), COALESCE_MS);
}

async function runQueuedRead(): Promise<void> {
  pending = null;
  if (!queued.read || startupWait) return;
  const lists = queued.lists;
  queued.read = queued.lists = false;
  reading = true;
  aggregateCovered = true;
  try {
    if (lists) await refreshLists();
    aggregateCovered = huddle.selected === AGGREGATE || aggregateHolds > 0;
    await refreshList();
  } finally {
    reading = false;
    aggregateCovered = false;
    if (queued.read) armRead();
  }
}

function runReadNow(): void {
  if (pending) clearTimeout(pending);
  pending = null;
  if (!reading) void runQueuedRead();
}

function socketExpected(): boolean {
  const events = (globalThis as { AppEvents?: { subscribe?: unknown } }).AppEvents;
  return typeof events?.subscribe === 'function';
}

function startupArrived(part: keyof typeof startupGate): void {
  startupGate[part] = true;
  if (startupGate.hello && startupGate.prefs) endStartupWait();
}

function endStartupWait(): void {
  if (!startupWait) return;
  clearTimeout(startupWait);
  startupWait = null;
  runReadNow();
}

export function startTaskManager(initial: string | null = null): void {
  if (started) return;
  started = true;
  if (initial) huddle.selected = initial;
  const push = resourcePush();
  let livenessMoved = false;
  push.onChange((topics) => {
    livenessMoved = topics.includes(LIVENESS);
    if (!deltaLive() && topics.some((topic) => familyOf(topic) === TASK_MANAGER_FAMILY)) scheduleRefresh();
  });
  push.pushOrPoll(() => {
    if (!deltaLive() || livenessMoved) scheduleRefresh();
    startupArrived('hello');
  }, POLL_MS, [`${TASK_MANAGER_FAMILY}:${ALL_LIST}`]);
  onEventFrame(DATA_FRAME, deltaLanes.receive);
  followPrefs();
  onViewChange(() => scheduleRefresh());
  onHideCompletedChange((hide) => {
    if (hide !== hideReadWith) scheduleRefresh();
  });
  void paintFromCache();
  scheduleRefresh();
  startupGate.hello = !socketExpected() || pushIsLive();
  startupWait = setTimeout(endStartupWait, STARTUP_WAIT_MS);
  void prefsSettled().then(() => startupArrived('prefs'));
}

async function paintFromCache(): Promise<void> {
  const snap = await readTaskManagerSnapshot();
  if (!snap || huddle.status !== 'idle') return;
  if (huddle.selected === AGGREGATE) {
    if (huddle.groups === null && snap.aggregate) huddle.groups = snap.aggregate;
  } else {
    const body = snap.bodies[huddle.selected];
    if (huddle.body === null && body) huddle.body = body;
  }
}

export async function openOnProject(key: string | null): Promise<void> {
  if (!key || !huddle.lists.some((row) => row.key === key)) return;
  huddle.addTarget = key;
  await selectList(key);
}

export function toggleRow(id: number): void {
  huddle.openId = huddle.openId === id ? null : id;
  if (openThread.id !== huddle.openId) openThread.id = null;
}

export function itemsOnScreen(): HuddleItem[] {
  return huddle.groups ? huddle.groups.flatMap((g) => g.items) : (huddle.body?.items ?? []);
}

export function findItem(id: number): HuddleItem | null {
  return itemsOnScreen().find((i) => i.id === id) ?? null;
}

export async function markRead(item: HuddleItem): Promise<void> {
  await heldRead(item)?.send();
}

/* nothing was written */
export function heldRead(item: HuddleItem): { undo: Undo; send: () => Promise<void> } | null {
  if (!needsSeen(item)) return null;
  const through = boundaryOf(item);
  const undoView = applyMarkRead(item, through);
  const release = holdRead(item.id, through);
  const undo: Undo = () => { release(); undoView(); };
  const send = async (): Promise<void> => {
    try {
      await trackWrite(() => authFetch(`/cplugs/huddle/items/${item.id}/seen`, { method: 'POST', body: JSON.stringify(through === undefined ? {} : { through }) }));
    } catch (error) {
      undo();
      console.warn('huddle: could not mark the item read', error);
    } finally {
      release();
    }
  };
  return { undo, send };
}

function setUnread(item: HuddleItem, kind: TaskManagerPostKind, count: number): void {
  const meta = POST_KINDS[kind];
  item[meta.countField] = Math.max(0, count);
  item[meta.flagField] = count > 0;
}

const postSeen = (itemId: number, messageId: number): Promise<unknown> =>
  trackWrite(() => authFetch(`/cplugs/huddle/items/${itemId}/seen`, { method: 'POST', body: JSON.stringify({ message: messageId }) }));

export async function readPost(item: HuddleItem, message: TaskManagerMessage): Promise<void> {
  const kind: TaskManagerPostKind | null = postKindOf(message);
  if (!kind || !message.unread) return;
  const before = unreadCount(item, kind);
  message.unread = false;
  setUnread(item, kind, before - 1);
  try {
    await postSeen(item.id, message.id);
  } catch (error) {
    message.unread = true;
    setUnread(item, kind, before);
    console.warn('huddle: could not mark the post read', error);
  }
}

export async function selectList(key: string): Promise<void> {
  const shown = key === AGGREGATE ? huddle.groups !== null : huddle.body?.list === key;
  if (huddle.selected === key && shown) return;
  huddle.selected = key;
  huddle.body = null;
  if (aggregateHolds === 0) huddle.groups = null;
  await refreshList();
}

export function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const code = refusalCode(error.payload);
    const lock = lockFromPayload(error.payload);
    if (lock) return lockReason(lock, t);
    if (code) {
      const key = `cplug.huddle.refused.${code}`;
      const reason = (error.payload as { detail?: { detail?: unknown } } | null)?.detail?.detail;
      const text = t(key, { reason: typeof reason === 'string' && reason ? reason : error.message });
      return text === key ? error.message : text;
    }
    return error.message;
  }
  return t('cplug.huddle.refused.failed');
}

export function pushIsLive(): boolean {
  return resourcePush().isLive?.(`${TASK_MANAGER_FAMILY}:${ALL_LIST}`) === true;
}

export async function write(run: () => Promise<unknown>, undo?: Undo): Promise<boolean> {
  huddle.notice = '';
  let accepted = false;
  try {
    await trackWrite(run);
    accepted = true;
  } catch (error) {
    undo?.();
    huddle.notice = explain(error);
  }
  if (!accepted || !undo || !pushIsLive()) void refreshTaskManager();
  return accepted;
}

export async function addItem(text: string): Promise<TaskManagerAddOutcome> {
  const key = huddle.addTarget;
  let outcome = 'queued' as TaskManagerAddOutcome;
  const landed = await write(async () => {
    const out = await outboxPost({
      kind: 'add', path: `/cplugs/huddle/lists/${seg(key)}/inbox`, body: { text }, idempotent: true, sendList: key,
      where: huddle.lists.find((l) => l.key === key)?.name ?? key, text, list: key, item: null,
    });
    if (out.kept) outcome = 'kept';
    else if (!(out.answer as { queued: boolean }).queued) outcome = 'added';
  });
  if (landed && outcome === 'kept') huddle.notice = t(keptNoticeKey());
  return landed ? outcome : 'failed';
}

export function completedLists(view: string = huddle.selected): { list: string; count: number }[] {
  const rows = view === AGGREGATE
    ? (huddle.groups ?? []).filter((g) => !isAgentList(g.list)).map((g) => ({ list: g.list, count: completedCount(g.items) }))
    : [{ list: view, items: huddle.body?.list === view ? huddle.body.items : huddle.groups?.find((g) => g.list === view)?.items }]
      .flatMap((one) => (one.items ? [{ list: one.list, count: completedCount(one.items) }] : []));
  return rows.filter((row) => row.count > 0);
}

export function removeCompleted(view: string = huddle.selected): Promise<boolean> {
  const lists = completedLists(view).map((row) => row.list);
  if (!lists.length) return Promise.resolve(true);
  return write(async () => {
    for (const list of lists) await authFetch(`/cplugs/huddle/lists/${seg(list)}/remove-completed`, { method: 'POST' });
  });
}

export function setApproved(item: HuddleItem, approved: boolean): Promise<boolean> {
  const undo = applyTick(findItem(item.id) ?? item, approved);
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, {
    method: 'PATCH', body: JSON.stringify({ approved, expected_revision: item.revision }),
  }), undo);
}

function staleRevision(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  const revision = (error.payload as { detail?: { current?: { revision?: unknown } } } | null)?.detail?.current?.revision;
  return typeof revision === 'number' ? revision : null;
}

export function approveWithNote(item: HuddleItem, note: string): Promise<boolean> {
  const undo = applyTick(findItem(item.id) ?? item, true);
  let revision = item.revision;
  return write(async () => {
    for (let attempt = 0; ; attempt += 1) {
      try {
        await authFetch(`/cplugs/huddle/items/${item.id}`, { method: 'PATCH', body: JSON.stringify({ note, approved: true, expected_revision: revision }) });
        return;
      } catch (error) {
        const current = staleRevision(error);
        if (current === null || attempt > 0) throw error;
        revision = current;
      }
    }
  }, undo);
}

export function setReviewCheck(item: HuddleItem, checkId: string, checked: boolean): Promise<boolean> {
  const undo = applyReviewCheck(findItem(item.id) ?? item, checkId, checked);
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}/review-checks/${seg(checkId)}`, {
    method: 'PATCH', body: JSON.stringify({ checked }),
  }), undo);
}

export function setBackBurner(item: HuddleItem, on: boolean): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, {
    method: 'PATCH', body: JSON.stringify({ state: on ? 'todo' : 'open', expected_revision: item.revision }),
  }));
}

export function saveSchedule(item: HuddleItem, change: { fire_at?: string; repeat?: TaskManagerRepeat | ''; paused?: boolean }): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, {
    method: 'PATCH', body: JSON.stringify({ ...change, expected_revision: item.revision }),
  }));
}

export function saveNote(item: HuddleItem, note: string): Promise<boolean> {
  if (note.trim() === item.note.trim()) return Promise.resolve(true);
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, {
    method: 'PATCH', body: JSON.stringify({ note, expected_revision: item.revision }),
  }));
}

export function saveTitle(item: HuddleItem, title: string): Promise<boolean> {
  if (title.trim() === (item.title ?? '').trim()) return Promise.resolve(true);
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, {
    method: 'PATCH', body: JSON.stringify({ title, expected_revision: item.revision }),
  }));
}

export function nudgeInboxEntry(entry: TaskManagerInboxEntry): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/inbox/${entry.id}/nudge`, { method: 'POST' }));
}

export function deleteItem(item: HuddleItem): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}`, { method: 'DELETE' }));
}

/* the server did not answer */
export async function reply(item: HuddleItem, text: string, files: readonly string[] = [], tells = true, comment = false): Promise<boolean | 'kept'> {
  const ackThrough = boundaryOf(findItem(item.id) ?? item);
  const body = { text, ...(files.length ? { files } : {}), ...(comment ? { kind: 'comment' } : {}), ...(!comment && ackThrough !== undefined ? { ack_through: ackThrough } : {}) };
  const undo = comment ? () => {} : applyReply(findItem(item.id) ?? item, text);
  let kept = false;
  const landed = await write(async () => {
    const out = await outboxPost({
      kind: 'reply', path: `/cplugs/huddle/items/${item.id}/messages`, body, idempotent: true, sendList: tells && !comment ? item.list : null,
      where: itemWhere(item), text, list: item.list, item: item.id,
    });
    if (out.kept) { kept = true; undo(); }
  }, undo);
  if (landed && kept) {
    huddle.notice = t(keptNoticeKey());
    return 'kept';
  }
  return landed;
}

export function acceptSchedule(item: HuddleItem, messageId: number): Promise<boolean> {
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}/messages/${messageId}/schedule`, { method: 'POST' }));
}

export function moveToList(item: HuddleItem, list: string, group?: number): Promise<boolean> {
  const body = group === undefined ? { list } : { list, group };
  return write(() => authFetch(`/cplugs/huddle/items/${item.id}/move`, { method: 'POST', body: JSON.stringify(body) }));
}

export function moveItem(from: number, to: number, list: string = huddle.selected): Promise<boolean> {
  const group = huddle.groups?.find((g) => g.list === list) ?? (huddle.body?.list === list ? huddle.body : null);
  if (!group || from === to) return Promise.resolve(true);
  return reorderList(moveId(group.items.map((i) => i.id), from, to), list);
}

export function reorderList(ids: readonly number[], list: string = huddle.selected): Promise<boolean> {
  const group = huddle.groups?.find((g) => g.list === list) ?? (huddle.body?.list === list ? huddle.body : null);
  if (!group) return Promise.resolve(true);
  const byId = new Map(group.items.map((i) => [i.id, i]));
  const positions = new Map(group.items.map((i) => [i.id, i.position]));
  const sorted = [...positions.values()].sort((a, b) => a - b);
  const items = ids.map((id, at) => ({ ...(byId.get(id) as HuddleItem), position: sorted[at] ?? at }));
  if (huddle.groups) huddle.groups = huddle.groups.map((g) => (g.list === list ? { ...g, items } : g));
  if (huddle.body?.list === list) huddle.body = { ...huddle.body, items };
  return write(() => authFetch(`/cplugs/huddle/lists/${seg(list)}/order`, {
    method: 'PUT', body: JSON.stringify({ ids, expected_revision: group.revision }),
  }));
}
