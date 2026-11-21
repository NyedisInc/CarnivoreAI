/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { VisitorResponse } from './visitors-api';

const push = vi.hoisted(() => ({
  listeners: [] as Array<{ refresh: () => void; topics: readonly string[] }>,
  polls: 0,
}));
const net = vi.hoisted(() => ({ authFetch: vi.fn() }));
vi.mock('../../sdk', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../sdk')>()),
  ...net,
  resourcePush: () => ({
    isLive: () => true,
    onChange: () => () => {},
    pushOrPoll: (refresh: () => void, _ms: number, topics: readonly string[]) => {
      const entry = { refresh, topics };
      push.listeners.push(entry);
      return () => { push.listeners = push.listeners.filter((e) => e !== entry); };
    },
  }),
}));

import VisitorsKey from './VisitorsKey.svelte';
import VisitorsModal from './VisitorsModal.svelte';

const TOPIC = 'cplug.reviewboard.visitors:nav';
let stored: VisitorResponse[] = [];
let app: ReturnType<typeof mount> | null = null;

function response(id: number, forwarded = false): VisitorResponse {
  return { id, revision: 'r1', kind: 'comment', name: null, created_at: 1_793_000_000 + id, forwarded_at: forwarded ? 1_793_000_900 : null,
    entries: [{ label: null, text: `words ${id}` }] };
}

async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
}

async function pushed(topic: string = TOPIC): Promise<void> {
  for (const entry of push.listeners.filter((e) => e.topics.includes(topic))) entry.refresh();
  await settle();
}

function reads(): number {
  return net.authFetch.mock.calls.filter(([path]) => String(path).startsWith('/cplugs/reviewboard/public/visitors?board=nav')).length;
}

beforeEach(() => {
  stored = [response(1, true)];
  push.listeners = [];
  net.authFetch.mockImplementation(async () => ({ responses: stored }));
});
let second: ReturnType<typeof mount> | null = null;
afterEach(() => {
  for (const one of [app, second]) if (one) unmount(one);
  app = null;
  second = null;
  document.body.innerHTML = '';
  vi.clearAllMocks();
});

describe('the visitors key', () => {
  it('wears the unforwarded count and follows the push', async () => {
    app = mount(VisitorsKey, { target: document.body, props: { slug: 'nav' } });
    await settle();
    expect(document.querySelector('[data-board-visitors-count]')).toBeNull();
    stored = [response(1, true), response(2), response(3)];
    await pushed();
    expect(document.querySelector('[data-board-visitors-count]')?.textContent).toBe('2');
  });
});

describe('the visitors window', () => {
  it('shows a new response when the push names the topic', async () => {
    app = mount(VisitorsModal, { target: document.body, props: { slug: 'nav', close: () => {} } });
    await settle();
    expect(document.body.textContent).not.toContain('words 2');
    stored = [response(1, true), response(2)];
    await pushed();
    expect(document.body.textContent).toContain('words 2');
  });
});

describe('one read per push', () => {
  it('the key and an open window share one read, and another board\'s push reads nothing', async () => {
    app = mount(VisitorsKey, { target: document.body, props: { slug: 'nav' } });
    second = mount(VisitorsModal, { target: document.body, props: { slug: 'nav', close: () => {} } });
    await settle();
    const opened = reads();
    expect(opened).toBe(1);
    await pushed();
    expect(reads()).toBe(opened + 1);
    await pushed('cplug.reviewboard.visitors:other');
    expect(reads()).toBe(opened + 1);
  });
});
