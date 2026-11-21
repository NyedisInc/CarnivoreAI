/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { ResourceTopicStore, pushOrPoll } from '../../lib/resource-push/store';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { registerBoardAttachments, resetBoardAttachments, subscribeBoardFiles, unregisterBoardAttachments, type BoardCardFile } from './board-attachments';

const TOPIC = 'cplug.reviewboard.boards';
const store = new ResourceTopicStore();
const stops: Array<ReturnType<typeof vi.fn>> = [];
vi.mock('../../lib/resource-push/boot', () => ({
  resourcePush: () => ({
    pushOrPoll: (refresh: () => void, ms: number, topics: readonly string[]) => {
      const off = pushOrPoll(store, refresh, ms, topics);
      const stop = vi.fn(off);
      stops.push(stop);
      return stop;
    },
  }),
}));

const file = (id: string, removed = false): BoardCardFile => ({ file_id: id, name: `${id}.pdf`, revision: 'r1', removed });
const tick = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); };

beforeEach(() => {
  store.closed();
  store.hello({ resource_topics: [TOPIC] });
});
afterEach(() => {
  resetBoardAttachments();
  stops.length = 0;
  store.closed();
});

describe('the board files store', () => {
  it('is driven by the topic the board plugin registered, not by a bare name', async () => {
    const read = vi.fn(async () => [file('a')]);
    registerBoardAttachments({ read, topic: TOPIC });
    const off = subscribeBoardFiles('b', () => undefined);
    await tick();
    expect(read).toHaveBeenCalledTimes(1);
    store.frame({ topics: ['boards'] });
    await tick();
    expect(read).toHaveBeenCalledTimes(1);
    store.frame({ topics: [TOPIC] });
    await tick();
    expect(read).toHaveBeenCalledTimes(2);
    off();
  });

  it('shares one read and one subscription across every card of a board, and a push reads once', async () => {
    const read = vi.fn(async () => [file('a')]);
    registerBoardAttachments({ read, topic: TOPIC });
    const seen: BoardCardFile[][] = [];
    const offs = Array.from({ length: 8 }, () => subscribeBoardFiles('b', (f) => seen.push(f)));
    await tick();
    expect(read).toHaveBeenCalledTimes(1);
    expect(stops).toHaveLength(1);
    expect(seen).toHaveLength(8);
    store.frame({ topics: [TOPIC] });
    await tick();
    expect(read).toHaveBeenCalledTimes(2);
    offs.forEach((off) => off());
  });

  it('a late card gets the last answer without a new read', async () => {
    const read = vi.fn(async () => [file('a')]);
    registerBoardAttachments({ read, topic: TOPIC });
    const first = subscribeBoardFiles('b', () => undefined);
    await tick();
    const late = vi.fn();
    const second = subscribeBoardFiles('b', late);
    expect(late).toHaveBeenCalledWith([file('a')]);
    expect(read).toHaveBeenCalledTimes(1);
    first();
    second();
  });

  it('an older answer that lands after a newer one publishes nothing', async () => {
    const answers: Array<(files: BoardCardFile[]) => void> = [];
    const read = vi.fn(() => new Promise<BoardCardFile[]>((resolve) => { answers.push(resolve); }));
    registerBoardAttachments({ read, topic: TOPIC });
    const seen: BoardCardFile[][] = [];
    const off = subscribeBoardFiles('b', (f) => seen.push(f));
    store.frame({ topics: [TOPIC] });
    expect(answers).toHaveLength(2);
    answers[1]!([file('a', true)]);
    await tick();
    answers[0]!([file('a', false)]);
    await tick();
    expect(seen.at(-1)).toEqual([file('a', true)]);
    expect(seen).toHaveLength(1);
    off();
  });

  it('the last card out stops the subscription, and a later push reads nothing', async () => {
    const read = vi.fn(async () => [file('a')]);
    registerBoardAttachments({ read, topic: TOPIC });
    const one = subscribeBoardFiles('b', () => undefined);
    const two = subscribeBoardFiles('b', () => undefined);
    await tick();
    one();
    expect(stops[0]).not.toHaveBeenCalled();
    two();
    expect(stops[0]).toHaveBeenCalledTimes(1);
    store.frame({ topics: [TOPIC] });
    await tick();
    expect(read).toHaveBeenCalledTimes(1);
  });

  it('tells a card the list is empty when the board plugin goes off, and keeps the list on a refusal', async () => {
    let on = true;
    let refuse = false;
    const read = vi.fn(async () => { if (refuse) throw new ApiError('HTTP 404', 404); return [file('a')]; });
    registerBoardAttachments({ read, topic: TOPIC }, () => on);
    const seen: BoardCardFile[][] = [];
    const off = subscribeBoardFiles('b', (f) => seen.push(f));
    await tick();
    refuse = true;
    store.frame({ topics: [TOPIC] });
    await tick();
    expect(seen.at(-1)).toEqual([file('a')]);
    on = false;
    store.frame({ topics: [TOPIC] });
    await tick();
    expect(seen.at(-1)).toEqual([]);
    off();
  });

  it('a card subscribed before the plugin registers is armed on the real topic, so a push then reads', async () => {
    const read = vi.fn(async () => [file('a')]);
    const seen: BoardCardFile[][] = [];
    const off = subscribeBoardFiles('b', (f) => seen.push(f));
    await tick();
    expect(seen.at(-1)).toEqual([]);
    expect(stops).toHaveLength(0);
    registerBoardAttachments({ read, topic: TOPIC });
    await tick();
    expect(read).toHaveBeenCalledTimes(1);
    expect(seen.at(-1)).toEqual([file('a')]);
    store.frame({ topics: [TOPIC] });
    await tick();
    expect(read).toHaveBeenCalledTimes(2);
    off();
  });

  it('unregistering tells every card of every slug an empty list at once, and stops their subscriptions', async () => {
    registerBoardAttachments({ read: async () => [file('a')], topic: TOPIC });
    const one: BoardCardFile[][] = [];
    const two: BoardCardFile[][] = [];
    const offs = [subscribeBoardFiles('b', (f) => one.push(f)), subscribeBoardFiles('b', (f) => two.push(f)), subscribeBoardFiles('c', () => undefined)];
    await tick();
    unregisterBoardAttachments();
    expect(one.at(-1)).toEqual([]);
    expect(two.at(-1)).toEqual([]);
    expect(stops).toHaveLength(2);
    expect(stops.every((s) => s.mock.calls.length === 1)).toBe(true);
    offs.forEach((off) => off());
  });

  it('a newer read that fails keeps the older read that succeeds, and a read in flight at switch-off publishes nothing', async () => {
    const answers: Array<{ ok: (f: BoardCardFile[]) => void; fail: () => void }> = [];
    const read = vi.fn(() => new Promise<BoardCardFile[]>((ok, no) => { answers.push({ ok, fail: () => no(new ApiError('HTTP 500', 500)) }); }));
    registerBoardAttachments({ read, topic: TOPIC });
    const seen: BoardCardFile[][] = [];
    const off = subscribeBoardFiles('b', (f) => seen.push(f));
    store.frame({ topics: [TOPIC] });
    answers[1]!.fail();
    await tick();
    answers[0]!.ok([file('a')]);
    await tick();
    expect(seen.at(-1)).toEqual([file('a')]);
    store.frame({ topics: [TOPIC] });
    unregisterBoardAttachments();
    answers[2]!.ok([file('late')]);
    await tick();
    expect(seen.at(-1)).toEqual([]);
    off();
  });

  it('registering the same source again (the host re-runs start) makes no read and no new subscription', async () => {
    const read = vi.fn(async () => [file('a')]);
    const source = { read, topic: TOPIC };
    registerBoardAttachments(source);
    const off = subscribeBoardFiles('b', () => undefined);
    await tick();
    registerBoardAttachments(source);
    registerBoardAttachments(source, () => true);
    await tick();
    expect(read).toHaveBeenCalledTimes(1);
    expect(stops).toHaveLength(1);
    off();
  });
});
