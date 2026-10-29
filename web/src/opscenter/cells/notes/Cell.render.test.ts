/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const fake = vi.hoisted(() => {
  class FakeApiError extends Error {
    readonly status: number;
    readonly code: string | null;
    readonly payload: unknown;
    constructor(
      message: string,
      status: number,
      code: string | null = null,
      payload: unknown = null,
    ) {
      super(message);
      this.name = 'ApiError';
      this.status = status;
      this.code = code;
      this.payload = payload;
    }
  }
  return {
    FakeApiError,
    calls: [] as Array<{ path: string; method: string; body: unknown }>,
    answers: [] as unknown[],
    primary: 'ses_1',
  };
});

const { FakeApiError, calls } = fake;

vi.mock('../../api/auth.svelte', () => ({
  // The widget shell's settings read reaches the poll module, which names these two at import (item 1048).
  auth: { state: 'unknown' },
  initAuth: () => {},
  ApiError: fake.FakeApiError,
  authFetch: (path: string, init: RequestInit = {}) => {
    fake.calls.push({
      path,
      method: (init.method ?? 'GET').toUpperCase(),
      body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
    });
    const answer = fake.answers.shift();
    if (answer instanceof Error) return Promise.reject(answer);
    return Promise.resolve(
      answer ?? { status: 'unchanged', body: '', revision: 0, updated_at: null },
    );
  },
}));

vi.mock('../../api/events.svelte', () => ({
  subscribe: () => () => {},
}));

vi.mock('../../api/host', () => ({
  primarySessionId: () => fake.primary,
}));

vi.mock('../../api', () => ({
  primarySessionId: () => fake.primary,
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
import CellWithHost from '../../shell/fixtures/CellWithHost.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { acquire, reset } from '../../api/notes.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import { META } from '../../engine/meta';

/** A server answer shaped like the endpoint's. */
function answer(body: string, revision: number, status = 'unchanged') {
  return { status, body, revision, updated_at: '2026-09-20T12:00:00+00:00' };
}

function draw(height = 400) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(Cell, {
    target,
    props: { width: 400, height, meta: META.notes, instance: 'notes' },
  });
  flushSync();
  return { target, app };
}

function installStorage(seed: Record<string, string> = {}) {
  const map = new Map(Object.entries(seed));
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    writable: true,
    value: {
      getItem: (key: string): string | null => map.get(key) ?? null,
      setItem: (key: string, value: string): void => void map.set(key, value),
      removeItem: (key: string): void => void map.delete(key),
    },
  });
  return map;
}

beforeEach(() => {
  vi.useFakeTimers();
  calls.length = 0;
  fake.answers = [];
  fake.primary = 'ses_1';
  installStorage();
  reset();
});

afterEach(() => {
  vi.useRealTimers();
  document.body.innerHTML = '';
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

describe('one notepad on screen', () => {
  test('the grid cell mounting closes an open notes drawer through its own close', async () => {
    const { openDrawer, registerOccupant, resetRightDrawerForTest, rightDrawer } =
      await import('../../../lib/right-drawer/dock.svelte');
    resetRightDrawerForTest();
    const el = document.createElement('div');
    const close = vi.fn(() => { rightDrawer.kind = null; });
    registerOccupant('notes', { root: el, box: el, close });
    openDrawer('notes');
    const { app } = draw();
    expect(close).toHaveBeenCalledOnce();
    unmount(app, { outro: false });

    openDrawer('notes');
    const target = document.createElement('div');
    document.body.appendChild(target);
    const inDrawer = mount(Cell, { target, props: { width: 300, height: 400, meta: META.notes, instance: 'notes', phone: true } });
    flushSync();
    expect(close).toHaveBeenCalledOnce();
    unmount(inDrawer, { outro: false });
    resetRightDrawerForTest();
  });
});

describe('what the cell draws in each state', () => {
  test('follows the SELECTED terminal cell, the page terminal by default', async () => {
    // the page terminal
    fake.answers = [answer('page note', 1), answer('web note', 4)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(calls[0]?.path).toBe('/sessions/cloude_api/note');

    inputFocus.claim('terminal:ses_2');
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(calls[1]?.path).toBe('/sessions/cloude_web/note');
    expect((target.querySelector('textarea') as HTMLTextAreaElement).value).toBe('web note');

    inputFocus.release('terminal:ses_2');
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toHaveLength(2);
    inputFocus.forget('terminal:ses_2');
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    expect(calls[2]?.path).toBe('/sessions/cloude_api/note');
    unmount(app, { outro: false });
  });

  test('reads the primary session by its WRAPPER field and shows the note', async () => {
    fake.answers = [answer('# todo', 2)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    expect(calls[0]?.path).toBe('/sessions/cloude_api/note');
    const box = target.querySelector('textarea') as HTMLTextAreaElement;
    expect(box).not.toBeNull();
    expect(box.value).toBe('# todo');
    unmount(app, { outro: false });
  });

  test('says there is no session rather than offering an empty box', async () => {
    fake.primary = '';
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    expect(target.querySelector('textarea')).toBeNull();
    expect(target.querySelector('[data-widget-note="none"]')).not.toBeNull();
    expect(calls).toEqual([]);
    unmount(app, { outro: false });
  });

  test('drops the toggle at the shortest height, keeps the disk and the text', async () => {
    fake.answers = [answer('note', 1)];
    const { target, app } = draw(80);
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    expect(target.querySelector('.oc-notes-mode')).toBeNull();
    expect(target.querySelector('[data-notes-save]')).not.toBeNull();
    expect(target.querySelector('textarea')).not.toBeNull();
    unmount(app, { outro: false });
  });
});

describe('typing, and where the keystrokes belong', () => {
  test('writes the note after the typing stops, at the revision it read', async () => {
    fake.answers = [answer('start', 4)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    calls.length = 0;

    const box = target.querySelector('textarea') as HTMLTextAreaElement;
    box.value = 'start, plus a line';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(calls).toEqual([]);

    fake.answers = [answer('start, plus a line', 5, 'committed')];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();

    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe('PUT');
    expect(calls[0]?.body).toEqual({ body: 'start, plus a line', expected_revision: 4 });
    expect(target.querySelector('[data-notes-save="saved"]')).not.toBeNull();
    unmount(app, { outro: false });
  });

  test('claims input ownership on focus and gives it back on the way out', async () => {
    fake.answers = [answer('note', 1)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    const box = target.querySelector('textarea') as HTMLTextAreaElement;
    box.dispatchEvent(new FocusEvent('focusin', { bubbles: true }));
    flushSync();
    expect(inputFocus.owner).toBe('notes');

    const body = target.querySelector('.oc-notes') as HTMLElement;
    body.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
    flushSync();
    expect(inputFocus.owner).toBeNull();
    unmount(app, { outro: false });
  });

  test('a blur writes the note without waiting out the debounce', async () => {
    fake.answers = [answer('start', 1)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    calls.length = 0;

    const box = target.querySelector('textarea') as HTMLTextAreaElement;
    box.value = 'typed and left';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    fake.answers = [answer('typed and left', 2, 'committed')];
    (target.querySelector('.oc-notes') as HTMLElement).dispatchEvent(
      new FocusEvent('focusout', { bubbles: true }),
    );
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    expect(calls).toHaveLength(1);
    expect(calls[0]?.body).toEqual({ body: 'typed and left', expected_revision: 1 });
    unmount(app, { outro: false });
  });
});

describe('the preview', () => {
  test('renders markdown as nodes, and a script tag as text', async () => {
    fake.answers = [answer('# head\n\n<script>alert(1)</script>', 1)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    (target.querySelector('[data-notes-mode="preview"]') as HTMLElement).click();
    flushSync();

    const view = target.querySelector('[data-notes-view="preview"]') as HTMLElement;
    expect(view).not.toBeNull();
    expect(view.querySelector('h1')?.textContent).toBe('head');
    expect(view.querySelector('script')).toBeNull();
    expect(view.textContent).toContain('<script>alert(1)</script>');
    expect(target.querySelector('textarea')).toBeNull();
    unmount(app, { outro: false });
  });

  test('remembers the toggle per device, and stores no note body', async () => {
    const stored = installStorage();
    fake.answers = [answer('a private note', 1)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    (target.querySelector('[data-notes-mode="preview"]') as HTMLElement).click();
    flushSync();

    expect([...stored.values()]).toEqual(['preview']);
    expect([...stored.values()].join('|')).not.toContain('a private note');
    unmount(app, { outro: false });
  });
});

describe('the conflict', () => {
  test('shows both texts and two named actions, and keeps the box editable', async () => {
    fake.answers = [answer('base', 1)];
    const { target, app } = draw();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    const box = target.querySelector('textarea') as HTMLTextAreaElement;
    box.value = 'mine';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();

    fake.answers = [
      new FakeApiError('stale', 409, null, {
        detail: { status: 'stale_revision', revision: 7, body: 'theirs', detail: 'another computer' },
      }),
    ];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();

    expect(target.querySelector('[data-notes-conflict="open"]')).not.toBeNull();
    expect(target.querySelector('[data-notes-action="theirs"]')).not.toBeNull();
    expect(target.querySelector('[data-notes-action="mine"]')).not.toBeNull();
    expect(target.querySelector('.oc-notes-theirs pre')?.textContent).toBe('theirs');
    expect((target.querySelector('textarea') as HTMLTextAreaElement).value).toBe('mine');

    (target.querySelector('[data-notes-action="theirs"]') as HTMLElement).click();
    flushSync();
    expect(target.querySelector('[data-notes-conflict="open"]')).toBeNull();
    const held = acquire('cloude_api').note;
    expect(held.body).toBe('theirs');
    expect(held.revision).toBe(7);
    unmount(app, { outro: false });
  });
});

describe('the widget menu', () => {
  test('declares edit, preview and save on its host slot, and a menu pick switches the mode', async () => {
    fake.answers = [answer('a note', 1)];
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(CellWithHost, { target, props: { slot: 'notes', cell: Cell, hostId: 'notes-host' } });
    flushSync();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();

    const declared = declaredActionsFor('notes-host');
    expect(declared.map((one) => one.id)).toEqual(['mode:edit', 'mode:preview', 'save']);
    expect(declared.find((one) => one.id === 'mode:edit')?.checked).toBe(true);

    declared.find((one) => one.id === 'mode:preview')?.run();
    flushSync();
    expect(declaredActionsFor('notes-host').find((one) => one.id === 'mode:preview')?.checked).toBe(true);

    unmount(app, { outro: false });
    flushSync();
    expect(declaredActionsFor('notes-host')).toEqual([]);
  });
});
