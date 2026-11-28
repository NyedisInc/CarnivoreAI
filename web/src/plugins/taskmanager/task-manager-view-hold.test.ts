/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import type { HuddleItem } from './huddle-model';
import { applyHold, placementOf, takeSnapshot } from './task-manager-view-hold';
import { createViewHold, HOLD_IDLE_MS, HOLD_LEAVE_MS, HOLD_SUSPEND_MS } from './task-manager-view-hold.svelte';

const mk = (id: number, section: string, position: number, extra: Partial<HuddleItem> = {}): HuddleItem => ({
  id, list: '1', text: `item ${id}`, note: '', position, created_by: 'claude', state: 'open', kind: '', number: null,
  revision: 1, created_seq: id, seq: id, deleted: false, thread: [], unread: false, group: null, status: section, section, ...extra,
} as unknown as HuddleItem);

describe('applyHold', () => {
  const before = [mk(1, 'open', 1), mk(2, 'question', 2), mk(3, 'working', 3)];
  const snap = takeSnapshot('sig', [['1', before]]);

  test('no snapshot or another signature draws live', () => {
    const live = [mk(9, 'open', 1)];
    expect(applyHold(null, 'sig', '1', live)).toBe(live);
    expect(applyHold(snap, 'other', '1', live)).toBe(live);
    expect(applyHold(snap, 'sig', 'unknown list', live)).toBe(live);
  });

  test('a task that changed section stays in its old place as it was drawn', () => {
    const live = [mk(1, 'open', 1), mk(2, 'review', 2), mk(3, 'working', 3)];
    const drawn = applyHold(snap, 'sig', '1', live);
    expect(drawn.map((i) => i.id)).toEqual([1, 2, 3]);
    expect(drawn[1]).toBe(before[1]);
  });

  test('a task whose place did not change draws live, so its text stays current', () => {
    const live = [mk(1, 'open', 1, { text: 'new words' }), before[1] as HuddleItem, before[2] as HuddleItem];
    expect(applyHold(snap, 'sig', '1', live)[0]?.text).toBe('new words');
  });

  test('a new task waits, a task that left stays, a moved position stays', () => {
    const live = [mk(1, 'open', 5), mk(4, 'open', 0), before[2] as HuddleItem];
    const drawn = applyHold(snap, 'sig', '1', live);
    expect(drawn.map((i) => i.id)).toEqual([1, 2, 3]);
    expect(drawn[0]).toBe(before[0]);
    expect(placementOf(drawn[1] as HuddleItem)).toBe(placementOf(before[1] as HuddleItem));
  });
});

describe('createViewHold', () => {
  const snap = takeSnapshot('sig', []);
  let at = 0;
  const hold = () => createViewHold(() => at);
  beforeEach(() => { vi.useFakeTimers(); at = 0; });
  afterEach(() => vi.useRealTimers());

  test('looking takes one snapshot and keeps it', () => {
    const h = hold();
    const take = vi.fn(() => snap);
    h.look(take); h.look(take);
    expect(h.snapshot).toBe(snap);
    expect(take).toHaveBeenCalledOnce();
  });

  test('leaving ends it after the leave delay, coming back before then keeps it', () => {
    const h = hold();
    h.look(() => snap);
    h.leave(); vi.advanceTimersByTime(HOLD_LEAVE_MS - 1); h.look(() => snap);
    vi.advanceTimersByTime(HOLD_LEAVE_MS); expect(h.snapshot).toBe(snap);
    h.leave(); vi.advanceTimersByTime(HOLD_LEAVE_MS); expect(h.snapshot).toBeNull();
  });

  test('idle ends it', () => {
    const h = hold();
    h.look(() => snap);
    vi.advanceTimersByTime(HOLD_IDLE_MS);
    expect(h.snapshot).toBeNull();
  });

  test('a pointer resting inside the list is never released by idle (round 7 jump)', () => {
    const h = hold();
    h.look(() => snap, true);
    vi.advanceTimersByTime(HOLD_IDLE_MS + 1_000);
    expect(h.snapshot).toBe(snap);
    h.leave(); vi.advanceTimersByTime(HOLD_LEAVE_MS);
    expect(h.snapshot).toBeNull();
  });

  test('the owner acting drops it at once and keeps it off while suspended, then looking arms again', () => {
    const h = hold();
    h.look(() => snap);
    h.act();
    expect(h.snapshot).toBeNull();
    at = HOLD_SUSPEND_MS - 1; h.look(() => snap);
    expect(h.snapshot).toBeNull();
    at = HOLD_SUSPEND_MS; h.look(() => snap);
    expect(h.snapshot).toBe(snap);
  });
});
