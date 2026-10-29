import { afterEach, beforeEach, expect, test, vi } from 'vitest';

const bridgeStub = vi.hoisted(() => ({ writeMany: vi.fn(), read: vi.fn(() => null), follow: vi.fn(() => () => {}) }));
vi.mock('../zone-shell/preference-field', () => ({ bridge: () => bridgeStub }));

import { flushReadState, markRead, unread } from './read-state.svelte';

beforeEach(() => {
  vi.useFakeTimers();
  bridgeStub.writeMany.mockReset();
  unread.read = [];
  unread.seenAt = null;
});
afterEach(() => vi.useRealTimers());

test('a mark during a pending write is written by a second flush', async () => {
  let release!: () => void;
  bridgeStub.writeMany.mockImplementationOnce(() => new Promise((r) => (release = () => r({ status: 'ok' }))));
  bridgeStub.writeMany.mockResolvedValue({ status: 'ok' });
  markRead(['run_1']);
  const flush = flushReadState();
  markRead(['run_2']);
  release();
  await flush;
  await vi.advanceTimersByTimeAsync(1500);
  expect(bridgeStub.writeMany).toHaveBeenCalledTimes(2);
  const last = bridgeStub.writeMany.mock.calls[1]![0] as { field: string; value: string[] }[];
  expect(last[0]!.value).toEqual(['run_1', 'run_2']);
});

test('a rejected write is retried and does not escape as an unhandled rejection', async () => {
  const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
  bridgeStub.writeMany.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ status: 'ok' });
  markRead(['run_1']);
  await flushReadState();
  expect(warn).toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(10_000);
  expect(bridgeStub.writeMany).toHaveBeenCalledTimes(2);
  warn.mockRestore();
});
