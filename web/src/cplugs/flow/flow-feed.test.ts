/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const server = vi.hoisted(() => ({ paths: [] as string[], answers: [] as unknown[], gate: null as null | Promise<void> }));

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      server.paths.push(path);
      if (server.gate) await server.gate;
      return server.answers.shift() ?? { ...base, items: [], full: false };
    },
  };
});

import { resourcePush } from '../sdk';
import { emptyFeed, mergeFeed, type FeedAnswer, type FeedItem } from './flow-model';
import FlowBody from './FlowBody.svelte';

const T = 1791743400;
const lanes = [
  { id: 'owner', kind: 'owner', label: 'owner', parent: null, depth: 0, color: null },
  { id: 's:b', kind: 'session', label: 'Daily Briefing', parent: null, depth: 0, color: 0 },
  { id: 's:f', kind: 'session', label: 'Fleet', parent: null, depth: 0, color: 1 },
  { id: 'a:1', kind: 'subagent', label: 'worker: Fix QNAP path', parent: 's:f', depth: 1, color: 2 },
];
const base = { seed: { kind: 'huddle_item', id: '395', title: 'qnap nightly backup broken' }, window: { start: T - 100, end: T + 5000 },
               lanes, cursor: T + 3000, total: 7, full: true, warnings: [] };
const items: FeedItem[] = [
  { id: 'crosstalk:m-N8jp', kind: 'crosstalk', lane: 's:b', to: 's:f', t: T + 255.1, u: T + 255.3, label: 'briefing asks fleet', landed: true, delivered: true, thread: 't-qA4j' },
  { id: 'work:s:f:call:tf1', kind: 'work', lane: 's:f', t: T + 270, u: T + 292.2, count: 3, tools: { huddle_add: 1, Agent: 1, crosstalk_reply: 1 }, duration_s: 22.2,
    calls: [{ tool: 'huddle_add', start: T + 270, end: T + 270.5 }] },
  { id: 'launch:launch:tf2', kind: 'launch', lane: 's:f', to: 'a:1', t: T + 290, u: T + 290.1, label: 'Fix QNAP path' },
  { id: 'a:1:say:1', kind: 'bubble', lane: 'a:1', t: T + 290.1, u: T + 290.1, role: 'task', text: 'do the thing' },
  { id: 'a:1:say:5', kind: 'bubble', lane: 'a:1', t: T + 2990, u: T + 2990, role: 'agent', text: 'done' },
  { id: 'return:return:tf2', kind: 'return', lane: 'a:1', to: 's:f', t: T + 3000, u: T + 3000, status: 'completed', duration_s: 2699.9, tool_count: 2 },
  { id: 'task:card:2', kind: 'task', lane: 's:b', t: T + 2995, u: T + 2995, label: 'item 395: in_progress -> review', change: 'moved', from_col: 'in_progress', to_col: 'review', item_id: 395 },
];

let app: ReturnType<typeof mount> | null = null;

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) {
    await Promise.resolve();
    await tick();
  }
  flushSync();
}

function entries(): string[] {
  return [...document.querySelectorAll('.flw-entry')].map((li) => li.querySelector('[data-flow-bubble], [data-flow-card]')?.textContent?.replace(/\s+/g, ' ').trim() ?? '');
}

beforeEach(() => {
  server.paths = [];
  server.gate = null;
  server.answers = [{ ...base, items: [...items].reverse() }];
  localStorage.setItem('carnivore.flow.seed', JSON.stringify({ kind: 'huddle_item', id: '395' }));
  resourcePush().store.hello({ resource_topics: ['crosstalk', 'cplug.flow.feed', 'cplug.huddle.list', 'cplug.huddle.cards'] });
  server.paths = [];
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
});

describe('flow chat view', () => {
  test('bubbles and cards in causal order, the subagent stepped in under its parent', async () => {
    app = mount(FlowBody, { target: document.body });
    await settle();
    expect(server.paths).toEqual(['/cplugs/flow/feed?seed=huddle_item&id=395']);
    const kinds = [...document.querySelectorAll('[data-flow-bubble], [data-flow-card]')].map((el) => el.getAttribute('data-flow-card') ?? `bubble:${el.getAttribute('data-flow-bubble')}`);
    expect(kinds).toEqual(['crosstalk', 'work', 'launch', 'bubble:task', 'bubble:agent', 'task', 'return']);
    expect(entries()[0]).toContain('Daily Briefing');
    expect(entries()[0]).toContain('Fleet');
    expect(entries()[0]).toContain('landed');
    const sub = [...document.querySelectorAll<HTMLElement>('.flw-entry')][3];
    expect(sub?.style.getPropertyValue('--_depth')).toBe('1');
    expect(document.querySelector('[data-flow-card="task"]')?.textContent).toContain('in_progress to review');
    expect(document.querySelector('.flw-calls')).toBeNull();
    (document.querySelector('[data-flow-card="work"] [data-flow-more]') as HTMLButtonElement).click();
    flushSync();
    expect(document.querySelector('.flw-calls')?.textContent).toContain('huddle_add');
  });

  test('a push reads after the cursor and appends; frames during a read coalesce into one more read', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'setTimeout'] });
    app = mount(FlowBody, { target: document.body });
    await settle();
    server.paths = [];
    let release!: () => void;
    server.gate = new Promise<void>((resolve) => { release = resolve; });
    server.answers = [
      { ...base, full: false, total: 8, cursor: T + 3500, items: [{ id: 's:f:say:9', kind: 'bubble', lane: 's:f', t: T + 3500, u: T + 3500, role: 'agent', text: 'backup path fixed' }] },
      { ...base, full: false, total: 8, cursor: T + 3500, items: [] },
    ];
    const push = resourcePush().store;
    push.frame({ topics: ['cplug.flow.feed'] });
    push.frame({ topics: ['crosstalk'] });
    push.frame({ topics: ['cplug.huddle.cards:8'] });
    push.frame({ topics: ['layouts'] });
    await settle();
    expect(server.paths).toHaveLength(1);
    expect(server.paths[0]).toContain(`cursor=${T + 3000}`);
    expect(server.paths[0]).toContain(`start=${T - 100}`);
    server.gate = null;
    release();
    await settle();
    expect(server.paths).toHaveLength(2);
    expect(entries().at(-1)).toContain('backup path fixed');
    vi.advanceTimersByTime(120_000);
    await settle();
    expect(server.paths).toHaveLength(2);
  });

  test('a pop-out link with item or session opens that seed on mount, ahead of the remembered one', async () => {
    window.history.replaceState(null, '', '/static/popout.html?tab=flow&item=412');
    try {
      server.answers = [{ ...base, seed: { kind: 'huddle_item', id: '412', title: 'x' }, items: [] }];
      app = mount(FlowBody, { target: document.body });
      await settle();
      expect(server.paths).toEqual(['/cplugs/flow/feed?seed=huddle_item&id=412']);
      expect(document.querySelector<HTMLInputElement>('[data-flow-seed-id]')?.value).toBe('412');
      unmount(app);
      app = null;
      server.paths = [];
      window.history.replaceState(null, '', '/static/popout.html?tab=flow&session=ses_abc');
      app = mount(FlowBody, { target: document.body });
      await settle();
      expect(server.paths).toEqual(['/cplugs/flow/feed?seed=session&id=ses_abc']);
    } finally {
      window.history.replaceState(null, '', '/');
    }
  });

  test('closing the page stops listening', async () => {
    app = mount(FlowBody, { target: document.body });
    await settle();
    unmount(app);
    app = null;
    server.paths = [];
    resourcePush().store.frame({ topics: ['cplug.flow.feed'] });
    await settle();
    expect(server.paths).toEqual([]);
  });

  test('a feed that lost an item asks for a whole read', () => {
    const held = emptyFeed();
    expect(mergeFeed(held, { ...base, items } as FeedAnswer).resync).toBe(false);
    expect(mergeFeed(held, { ...base, full: false, total: 6, items: [] } as FeedAnswer).resync).toBe(true);
    expect(held.ordered.map((i) => i.id)[0]).toBe('crosstalk:m-N8jp');
  });
});
