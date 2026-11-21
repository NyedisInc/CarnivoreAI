/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';

const push = vi.hoisted(() => ({ refresh: null as null | (() => void) }));
const net = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../../sdk', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../sdk')>()),
  ...net,
  resourcePush: () => ({ isLive: () => true, onChange: () => () => {}, pushOrPoll: (refresh: () => void) => { push.refresh = refresh; return () => {}; } }),
}));

import { followVisitors } from './visitors-feed.svelte';

interface Held { path: string; answer: (rows: Array<{ number: number }>) => void }

afterEach(() => { push.refresh = null; net.authFetch.mockReset(); });

function holdReads(): Held[] {
  const queue: Held[] = [];
  net.authFetch.mockImplementation((path: string) => new Promise((resolve) => {
    queue.push({ path, answer: (rows) => resolve({ responses: [], visitors: rows.map((r) => ({ label: `u${r.number}`, number: r.number, revision: 'r1', updated_at: 1 })) }) });
  }));
  return queue;
}

const flush = async (): Promise<void> => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };

describe('the shared visitors read', () => {
  it('reads again after a push that landed while a read was in flight, so the newest write is never missed', async () => {
    const queue = holdReads();
    const follow = followVisitors('nav');
    expect(queue).toHaveLength(1);
    push.refresh!();
    queue[0]!.answer([]);
    await flush();
    expect(queue).toHaveLength(2);
    queue[1]!.answer([{ number: 1 }]);
    await flush();
    expect(follow.feed.visitors.map((v) => v.number)).toEqual([1]);
    follow.stop();
  });

  it('several pushes during one flight cost one more read, not one each', async () => {
    const queue = holdReads();
    const follow = followVisitors('nav');
    push.refresh!(); push.refresh!(); push.refresh!();
    queue[0]!.answer([]);
    await flush();
    expect(queue).toHaveLength(2);
    queue[1]!.answer([{ number: 1 }]);
    await flush();
    expect(queue).toHaveLength(2);
    follow.stop();
  });

  it('a refresh with nothing in flight reads once', async () => {
    const queue = holdReads();
    const follow = followVisitors('nav');
    queue[0]!.answer([]);
    await flush();
    push.refresh!();
    expect(queue).toHaveLength(2);
    queue[1]!.answer([]);
    await flush();
    follow.stop();
  });
});
