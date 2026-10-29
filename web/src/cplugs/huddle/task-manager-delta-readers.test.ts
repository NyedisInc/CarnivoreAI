/** @vitest-environment jsdom */
import { afterAll, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, tick } from 'svelte';

const rig = vi.hoisted(() => {
  const handlers = new Set<(frame: { type?: string }) => void>();
  let hello: Record<string, unknown> | null = null;
  (globalThis as Record<string, unknown>).AppEvents = {
    subscribe(handler: (frame: { type?: string }) => void) {
      handlers.add(handler);
      return () => handlers.delete(handler);
    },
    isConnected: () => hello !== null,
    lastHello: () => hello,
  };
  return {
    calls: [] as string[],
    emit(frame: Record<string, unknown>) {
      if (frame.type === 'events.hello') hello = frame;
      for (const handler of [...handlers]) handler(frame);
    },
  };
});

const T = 1791743400;
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string, init: RequestInit = {}) => {
      if ((init.method ?? 'GET') === 'GET') rig.calls.push(path);
      if (path.startsWith('/cplugs/huddle/steps')) {
        return { lists: { '12': { items: { '7': { tasks: [], counts: { pending: 2, in_progress: 1, completed: 1 } } } } } };
      }
      if (path.includes('/boards')) {
        return { boards: [{ slug: 'b1', status: 'ok', title: 'board', revisions: 1, rounds: 0, state: 'closed', last_activity: null, project: '12',
                            closed_at: '2026-10-12T10:00:00Z', task_title: 'task nine', task: { item_id: 9, computer: 'm' } }] };
      }
      if (path.startsWith('/cplugs/flow/feed')) {
        return { seed: { kind: 'huddle_item', id: '42', title: 'seed' }, window: { start: T, end: T + 10 }, lanes: [], total: 1, full: true,
                 cursor: T + 5, warnings: [], items: [{ id: 'card:43', kind: 'huddle', lane: 'owner', t: T + 1, u: T + 1, item_id: 43 }] };
      }
      if (path.startsWith('/swarm/agents/5/conversation')) return { entries: [] };
      if (path.startsWith('/swarm/agents/5')) return { id: 5 };
      return {};
    },
  };
});

import { holdSteps } from './task-manager-steps.svelte';
import { createChatStore } from './chat/chat-store.svelte';
import { FlowFeed } from '../flow/flow-feed.svelte';
import ClosedReviews from '../reviewboard/ClosedReviews.svelte';

type Reader = 'steps' | 'chat' | 'flow' | 'closed';
function readerOf(path: string): Reader | null {
  if (path.startsWith('/cplugs/huddle/steps')) return 'steps';
  if (path.startsWith('/swarm/agents/5')) return 'chat';
  if (path.startsWith('/cplugs/flow/feed')) return 'flow';
  if (path.includes('/boards')) return 'closed';
  return null;
}

function reads(): Record<Reader, number> {
  const out: Record<Reader, number> = { steps: 0, chat: 0, flow: 0, closed: 0 };
  for (const path of rig.calls) {
    const reader = readerOf(path);
    if (reader) out[reader] += 1;
  }
  return out;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await new Promise((resolve) => setTimeout(resolve, 10));
    await tick();
    flushSync();
  }
}

const row = (id: number, list: string, state = 'open', status = 'open') => ({
  id, list, state, status, owner_session_key: '', text: `item ${id}`, note: '', position: id, created_by: 'claude', kind: 'task',
  lane: 'task_manager', revision: 2, created_seq: id, seq: id, deleted: false, number: 1, thread: [], thread_slim: true,
});

async function change(list: string, item: ReturnType<typeof row>, seq?: number): Promise<Record<Reader, number>> {
  rig.calls.length = 0;
  rig.emit({ type: 'resources.changed', topics: [`cplug.huddle.list:${list}`], seq: 1 });
  if (seq !== undefined) {
    rig.emit({
      type: 'cplug.data', topic: 'cplug.huddle.delta',
      data: { seq, epoch: 'e1', lists: [{ list, revision: seq, groups: [], inbox: null, order: [item.id], numbers: {}, swarm: [], items: [item], deleted: [] }] },
    });
  }
  await settle();
  return reads();
}

const TOPICS = ['cplug.huddle.list', 'swarm_agent', 'cplug.flow.feed', 'crosstalk', 'cplug.huddle.cards', 'cplug.reviewboard.boards'];

afterAll(() => {
  delete (globalThis as Record<string, unknown>).AppEvents;
});

describe('task manager readers on the item delta', () => {
  test('a change that is not theirs costs no read; one that is costs one targeted read', async () => {
    rig.emit({ type: 'events.hello', resource_topics: TOPICS });
    holdSteps();
    createChatStore(5).start();
    const feed = new FlowFeed();
    feed.open({ kind: 'huddle_item', id: '42' });
    feed.start();
    const header = createRawSnippet(() => ({ render: () => '<div></div>' }));
    mount(ClosedReviews, {
      target: document.body,
      props: { projectId: 12, projectKey: '12', header, isFolded: () => false, age: () => '', previewOf: (n: number) => n },
    });
    await settle();

    const before = await change('12', row(500, '12'));
    expect(before).toEqual({ steps: 1, chat: 0, flow: 1, closed: 1 });

    rig.emit({ type: 'events.hello', resource_topics: [...TOPICS, 'cplug.huddle.delta'] });
    await settle();

    const after = await change('12', row(500, '12'), 1);
    expect(after).toEqual({ steps: 0, chat: 0, flow: 0, closed: 0 });

    expect(await change('12', row(7, '12'), 2)).toEqual({ steps: 1, chat: 0, flow: 0, closed: 0 });
    expect(await change('12', row(9, '12'), 3)).toEqual({ steps: 0, chat: 0, flow: 0, closed: 1 });
    expect(await change('all', row(43, 'all'), 4)).toEqual({ steps: 0, chat: 0, flow: 1, closed: 0 });
    expect(await change('agent:5', row(600, 'agent:5'), 5)).toEqual({ steps: 0, chat: 2, flow: 0, closed: 0 });
    expect(await change('12', row(501, '12', 'done'), 6)).toEqual({ steps: 0, chat: 0, flow: 0, closed: 1 });
    expect(await change('12', row(501, '12', 'done'), 7)).toEqual({ steps: 0, chat: 0, flow: 0, closed: 0 });

    expect(await change('12', row(500, '12'), 9)).toEqual({ steps: 1, chat: 2, flow: 1, closed: 1 });
    console.info(`reads per change not theirs: before ${JSON.stringify(before)}, after ${JSON.stringify(after)}`);
  });
});
