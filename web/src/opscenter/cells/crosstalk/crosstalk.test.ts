/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const asked = vi.hoisted(() => [] as string[]);

const THREAD = {
  thread: 't-ab', message_count: 2, last_at: 2000, first_at: 1000, last_preview: 'ab two', last_sender_key: 'uuid-b',
  last_status: 'delivered',
  participants: [
    { key: 'uuid-a', id: 'ses_1', session_uuid: 'uuid-a', name: 'Alice', provider: 'claude', model: null, project_id: 4, project_name: 'api' },
    { key: 'uuid-b', id: 'ses_2', session_uuid: 'uuid-b', name: 'Bob', provider: 'codex', model: null, project_id: 4, project_name: 'api' },
  ],
};

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      asked.push(path);
      if (path.startsWith('/crosstalk/threads?')) return { threads: [THREAD], next_before: null };
      if (path.startsWith('/crosstalk/threads/t-ab/messages')) {
        return { thread: 't-ab', next_before: null, messages: [
          { id: 'm1', source: 'crosstalk', thread: 't-ab', sender_id: 'ses_1', sender_uuid: 'uuid-a', sender_name: 'Alice',
            sender_provider: 'claude', sender_model: '', receiver_id: 'ses_2', receiver_uuid: 'uuid-b', receiver_name: 'Bob',
            text: 'ab one', status: 'delivered', created_at: 1000 },
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
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { stateKey } from '../../widgets/shell/widget-state.svelte';
import { resourcePush } from '../../../lib/resource-push/boot';
import { filterFor, perspectiveOf, SCOPE_MEMORY_KEY } from '../../../lib/crosstalk/history/history-model';

const SCOPE = { sessionId: 'ses_1', rowId: 7, workingDir: '/w', projectId: 4 };
let host: HTMLElement;
let app: Record<string, unknown> | null = null;

async function settle(): Promise<void> {
  for (let turn = 0; turn < 5; turn += 1) {
    await Promise.resolve();
    flushSync();
  }
}

const lists = (): string[] => asked.filter((path) => path.startsWith('/crosstalk/threads?'));

const HOST = 'crosstalk-host';

const SCOPE_KEY = stateKey('core.crosstalk', 'scope');

async function show(scope: typeof SCOPE | null, height = 600): Promise<void> {
  app = mount(CellWithHost, { target: host, props: { slot: 'crosstalk', cell: Crosstalk, hostId: HOST, scope, height } }) as Record<string, unknown>;
  flushSync();
  await tick();
  await Promise.resolve();
  flushSync();
}

async function press(scope: string): Promise<void> {
  declaredActionsFor(HOST).find((one) => one.id === `scope:${scope}`)!.run();
  flushSync();
  await tick();
  await Promise.resolve();
  flushSync();
}

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
  vi.useRealTimers();
});

describe('the crosstalk widget scope switch', () => {
  test('lives in the widget menu, not the body, and the saved choice comes back', async () => {
    await show(SCOPE);
    expect(host.querySelector('[data-crosstalk-scope]')).toBeNull();
    const choices = () => declaredActionsFor(HOST).filter((one) => one.id.startsWith('scope:'));
    expect(choices().map((one) => [one.id, one.checked])).toEqual([['scope:all', false], ['scope:project', true], ['scope:session', false]]);
    await press('session');
    expect(choices().map((one) => one.checked)).toEqual([false, false, true]);
    expect(localStorage.getItem(SCOPE_KEY)).toBe('session');
    unmount(app!);
    await show(SCOPE);
    expect(choices().map((one) => one.checked)).toEqual([false, false, true]);
    expect(lists().at(-1)).toBe('/crosstalk/threads?session=ses_1&session_row=7&limit=50');
  });

  test('the choice kept before the widget declared its state still counts', async () => {
    localStorage.setItem(SCOPE_MEMORY_KEY, 'all');
    await show(SCOPE);
    expect(declaredActionsFor(HOST).find((one) => one.id === 'scope:all')?.checked).toBe(true);
    expect(lists().at(-1)).toBe('/crosstalk/threads?limit=50');
  });

  test('each scope asks for its own filter, and the choice is remembered on this device', async () => {
    await show(SCOPE);
    expect(lists()).toEqual(['/crosstalk/threads?project=4&limit=50']);
    await press('session');
    expect(lists().at(-1)).toBe('/crosstalk/threads?session=ses_1&session_row=7&limit=50');
    await press('all');
    expect(lists().at(-1)).toBe('/crosstalk/threads?limit=50');
    expect(localStorage.getItem(SCOPE_KEY)).toBe('all');
    const row = host.querySelector('[data-crosstalk-open="t-ab"]')?.textContent ?? '';
    expect(row).toContain('Bob');
    expect(row).toContain('Alice');
    expect(row.indexOf('Bob')).toBeLessThan(row.indexOf('Alice'));
  });

  test('a session with no project, or no session, says so and reads nothing', async () => {
    await show({ ...SCOPE, projectId: null as unknown as number });
    expect(lists()).toEqual([]);
    expect(host.querySelector('[data-widget-note]')?.textContent).toContain('has no project');
    unmount(app!);
    localStorage.setItem(SCOPE_MEMORY_KEY, 'session');
    await show(null);
    expect(lists()).toEqual([]);
    expect(host.querySelector('[data-widget-note]')?.textContent).toContain('pick a session');
  });

  test('it follows the selected session, re-reads on push with no idle timer, and opens a thread', async () => {
    vi.useFakeTimers();
    localStorage.setItem(SCOPE_MEMORY_KEY, 'session');
    await show(SCOPE);
    unmount(app!);
    await show({ ...SCOPE, sessionId: 'ses_2', rowId: 8 });
    expect(lists().at(-1)).toBe('/crosstalk/threads?session=ses_2&session_row=8&limit=50');
    const before = lists().length;
    vi.advanceTimersByTime(120000);
    expect(lists().length).toBe(before);
    resourcePush().store.frame({ topics: ['crosstalk'] });
    await Promise.resolve();
    expect(lists().length).toBe(before + 1);
    host.querySelector<HTMLButtonElement>('[data-crosstalk-open="t-ab"]')!.click();
    await settle();
    expect(asked.at(-1)).toBe('/crosstalk/threads/t-ab/messages');
    expect(host.querySelector('[data-message-id="m1"]')).not.toBeNull();
    expect(host.querySelector('[data-crosstalk-thread="t-ab"]')).not.toBeNull();
  });

  test('the back control is a small icon button, no visible text, in the title strip', async () => {
    localStorage.setItem(SCOPE_MEMORY_KEY, 'session');
    await show(SCOPE, 300);
    host.querySelector<HTMLButtonElement>('[data-crosstalk-open="t-ab"]')!.click();
    await settle();
    const back = host.querySelector<HTMLButtonElement>('[data-crosstalk-back]')!;
    expect(back).not.toBeNull();
    expect(back.dataset.size).toBe('icon');
    expect(back.getAttribute('aria-label')).toBe('back to the list');
    expect(back.title).toBe('back to the list');
    expect(back.textContent?.trim()).toBe('');
    expect(back.querySelector('svg[data-icon="chevron-left"]')).not.toBeNull();
    back.click();
    await settle();
    expect(host.querySelector('[data-crosstalk-back]')).toBeNull();
  });

  test('a thread is read as the target side when it is one, else as its first side', () => {
    expect(perspectiveOf(THREAD, { sessionId: 'ses_2' }).name).toBe('Bob');
    expect(perspectiveOf(THREAD, null).name).toBe('Alice');
    expect(filterFor('session', { rowId: 7 })).toEqual({ filter: { session_row: 7 } });
  });
});
