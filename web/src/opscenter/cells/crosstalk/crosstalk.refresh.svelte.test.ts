/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const asked = vi.hoisted(() => [] as string[]);

const thread = (id: string, lastAt: number) => ({
  thread: id, message_count: 1, last_at: lastAt, first_at: lastAt - 10, last_preview: `${id} text`, last_sender_key: 'uuid-b',
  last_status: 'delivered',
  participants: [
    { key: 'uuid-a', id: 'ses_1', session_uuid: 'uuid-a', name: 'Alice', provider: 'claude', model: null, project_id: 4, project_name: 'api' },
    { key: 'uuid-b', id: 'ses_2', session_uuid: 'uuid-b', name: 'Bob', provider: 'codex', model: null, project_id: 4, project_name: 'api' },
  ],
});

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      asked.push(path);
      if (path.startsWith('/crosstalk/threads?')) return { threads: [thread('t-new', 2000), thread('t-old', 1500)], next_before: null };
      const id = /\/crosstalk\/threads\/([^/]+)\/messages/.exec(path)?.[1];
      if (id) {
        return { thread: id, next_before: null, messages: [
          { id: `${id}-m1`, source: 'crosstalk', thread: id, sender_id: 'ses_1', sender_uuid: 'uuid-a', sender_name: 'Alice',
            receiver_id: 'ses_2', receiver_uuid: 'uuid-b', receiver_name: 'Bob', text: `${id} one`, status: 'delivered', created_at: 1000 },
        ] };
      }
      return {};
    },
  };
});

globalThis.ResizeObserver ??= class { observe(): void {} unobserve(): void {} disconnect(): void {} } as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= (): void => {};
(globalThis as { CSS?: unknown }).CSS ??= { escape: (value: string) => value };

import Crosstalk from './Cell.svelte';
import CellWithHost from '../../shell/fixtures/CellWithHost.svelte';
import { resourcePush } from '../../../lib/resource-push/boot';

const SCOPE = { sessionId: 'ses_1', rowId: 7, workingDir: '/w', projectId: 4 };
let host: HTMLElement;
let app: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
  for (let turn = 0; turn < 5; turn += 1) {
    await tick();
    await Promise.resolve();
    flushSync();
  }
}

const lists = (): string[] => asked.filter((path) => path.startsWith('/crosstalk/threads?'));

beforeEach(() => {
  asked.length = 0;
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  resourcePush().store.hello({ resource_topics: ['crosstalk'] });
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  host.remove();
});

describe('a listing push with the same scope', () => {
  test.each([['stacked', 600], ['drilled in', 240]])('keeps the %s conversation the owner picked, and reads nothing', async (_form, height) => {
    const props = $state({ slot: 'crosstalk' as const, cell: Crosstalk, hostId: 'crosstalk-refresh', scope: { ...SCOPE }, height });
    app = mount(CellWithHost, { target: host, props }) as Record<string, unknown>;
    await settle();
    host.querySelector<HTMLButtonElement>('[data-crosstalk-open="t-old"]')!.click();
    await settle();
    expect(host.querySelector('[data-crosstalk-thread="t-old"]')).not.toBeNull();
    const before = asked.length;
    const listsBefore = lists().length;

    for (let push = 0; push < 3; push += 1) {
      props.scope = { ...SCOPE };
      await settle();
    }

    expect(lists().length).toBe(listsBefore);
    expect(asked.length).toBe(before);
    expect(host.querySelector('[data-crosstalk-thread="t-old"]')).not.toBeNull();
    expect(host.querySelector('[data-crosstalk-thread="t-new"]')).toBeNull();

    props.scope = { ...SCOPE, sessionId: 'ses_9', projectId: 5 };
    await settle();
    expect(lists().at(-1)).toBe('/crosstalk/threads?project=5&limit=50');
  });
});
