/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const fake = vi.hoisted(() => ({
  calls: [] as Array<{ path: string; method: string; body: unknown }>,
  notes: { '/sessions/cloude_api/note': { body: 'api note', revision: 2 }, '/sessions/cloude_web/note': { body: 'web note', revision: 5 } } as Record<string, { body: string; revision: number }>,
  frame: null as ((frame: unknown) => void) | null,
}));

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'unknown' },
  initAuth: () => {},
  ApiError: class extends Error {},
  authFetch: (path: string, init: RequestInit = {}) => {
    const method = (init.method ?? 'GET').toUpperCase();
    fake.calls.push({ path, method, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
    const held = fake.notes[path];
    if (method === 'PUT') {
      const sent = JSON.parse(String(init.body)) as { body: string };
      if (held) fake.notes[path] = { body: sent.body, revision: held.revision + 1 };
      return Promise.resolve({ status: 'committed', ...fake.notes[path], updated_at: null });
    }
    return Promise.resolve({ status: 'unchanged', ...held, updated_at: null });
  },
}));

vi.mock('../../api/events.svelte', () => ({
  subscribe: (_kind: string, handler: (frame: unknown) => void) => {
    fake.frame = handler;
    return () => {};
  },
}));
vi.mock('../../api/host', () => ({ primarySessionId: () => 'ses_1' }));
vi.mock('../../api', () => ({
  primarySessionId: () => 'ses_1',
  sessions: {
    get data() {
      return [
        { session: { id: 'ses_1' }, tmux_session: 'cloude_api' },
        { session: { id: 'ses_2' }, tmux_session: 'cloude_web' },
      ];
    },
  },
}));

import Cell from './Cell.svelte';
import { reset } from '../../api/notes.svelte';
import { META } from '../../engine/meta';

function draw(instance: string, sessionId: string | null) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const props = { width: 400, height: 400, meta: META.notes, instance, ...(sessionId ? { scope: { sessionId } } : {}) };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the test hands the cell the same props the grid does
  const app = mount(Cell, { target, props: props as any });
  flushSync();
  return { target, app };
}

function boxOf(target: HTMLElement): string {
  return (target.querySelector('textarea') as HTMLTextAreaElement).value;
}

async function settle(): Promise<void> {
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
}

beforeEach(() => {
  vi.useFakeTimers();
  fake.calls.length = 0;
  fake.notes['/sessions/cloude_api/note'] = { body: 'api note', revision: 2 };
  fake.notes['/sessions/cloude_web/note'] = { body: 'web note', revision: 5 };
  fake.frame = null;
  reset();
});
afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
});

describe('two notes widgets', () => {
  test('each shows its own session note, and an edit in one never reaches the other', async () => {
    const a = draw('notes:a', 'ses_1');
    const b = draw('notes:b', 'ses_2');
    await settle();
    expect(boxOf(a.target)).toBe('api note');
    expect(boxOf(b.target)).toBe('web note');

    const box = b.target.querySelector('textarea') as HTMLTextAreaElement;
    box.value = 'web note edited';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    const put = fake.calls.find((c) => c.method === 'PUT');
    expect(put?.path).toBe('/sessions/cloude_web/note');
    expect(put?.body).toEqual({ body: 'web note edited', expected_revision: 5 });
    expect(boxOf(a.target)).toBe('api note');
    unmount(a.app, { outro: false });
    unmount(b.app, { outro: false });
  });

  test('a widget with no session chosen follows the primary session, beside one bound to another', async () => {
    const lone = draw('notes:lone', null);
    const other = draw('notes:other', 'ses_2');
    await settle();
    expect(boxOf(lone.target)).toBe('api note');
    expect(boxOf(other.target)).toBe('web note');
    unmount(lone.app, { outro: false });
    unmount(other.app, { outro: false });
  });

  test('two widgets on the same session share one read and one note', async () => {
    const a = draw('notes:a', 'ses_1');
    const b = draw('notes:b', 'ses_1');
    await settle();
    expect(fake.calls.filter((c) => c.method === 'GET')).toHaveLength(1);
    expect(boxOf(a.target)).toBe('api note');
    expect(boxOf(b.target)).toBe('api note');
    unmount(a.app, { outro: false });
    unmount(b.app, { outro: false });
  });

  test('a widget going away writes its unsaved edit, and the session note is read again when another widget comes back', async () => {
    const a = draw('notes:a', 'ses_1');
    await settle();
    const box = a.target.querySelector('textarea') as HTMLTextAreaElement;
    box.value = 'api note edited';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    unmount(a.app, { outro: false });
    await settle();
    expect(fake.calls.find((c) => c.method === 'PUT')?.body).toEqual({ body: 'api note edited', expected_revision: 2 });

    fake.calls.length = 0;
    const again = draw('notes:again', 'ses_1');
    await settle();
    expect(fake.calls.filter((c) => c.method === 'GET')).toHaveLength(1);
    expect(boxOf(again.target)).toBe('api note edited');
    unmount(again.app, { outro: false });
  });
});
