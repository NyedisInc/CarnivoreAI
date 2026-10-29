/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const fake = vi.hoisted(() => {
  class FakeApiError extends Error {
    readonly status: number;
    readonly code: string | null;
    readonly payload: unknown;
    constructor(message: string, status: number, code: string | null = null, payload: unknown = null) {
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
  };
});

const { FakeApiError, calls } = fake;

vi.mock('../../api/auth.svelte', () => ({
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
    if (answer instanceof Promise) return answer;
    return Promise.resolve(answer ?? { status: 'unchanged', body: '', revision: 0, updated_at: null });
  },
}));

vi.mock('../../api/events.svelte', () => ({ subscribe: () => () => {} }));
vi.mock('../../api/host', () => ({ primarySessionId: () => 'ses_1' }));
vi.mock('../../api', () => ({
  primarySessionId: () => 'ses_1',
  sessions: { get data() { return [{ session: { id: 'ses_1' }, tmux_session: 'cloude_api' }]; } },
}));

import Cell from './Cell.svelte';
import NotesDrawer from '../../../lib/notes-header/NotesDrawer.svelte';
import { reset } from '../../api/notes.svelte';
import { META } from '../../engine/meta';
import { matchGolden } from '../../../lib/zone-shell/fixtures/golden';
import { openDrawer, resetRightDrawerForTest } from '../../../lib/right-drawer/dock.svelte';

function answer(body: string, revision: number, status = 'unchanged') {
  return { status, body, revision, updated_at: '2026-10-12T12:00:00+00:00' };
}

async function drawLoaded(body = 'start') {
  fake.answers = [answer(body, 1)];
  const target = document.createElement('div');
  document.body.appendChild(target);
  const app = mount(Cell, { target, props: { width: 400, height: 400, meta: META.notes, instance: 'notes' } });
  flushSync();
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  calls.length = 0;
  return { target, app };
}

function held(): { promise: Promise<unknown>; release: (value: unknown) => void } {
  let release: (value: unknown) => void = () => {};
  const promise = new Promise<unknown>((resolve) => { release = resolve; });
  return { promise, release };
}

function puts(): Array<{ path: string; method: string; body: unknown }> {
  return calls.filter((call) => call.method === 'PUT');
}

async function drawDrawerLoaded(body = 'start') {
  fake.answers = [answer(body, 1)];
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  const target = document.createElement('div');
  document.body.appendChild(target);
  openDrawer('notes');
  const app = mount(NotesDrawer, {
    target,
    props: { onClose: () => {}, onComponent: () => {}, canComponent: () => false },
  });
  flushSync();
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  calls.length = 0;
  return { target, app };
}

function disk(target: HTMLElement): HTMLElement {
  return target.querySelector('[data-notes-save]') as HTMLElement;
}

function type(target: HTMLElement, text: string): void {
  const box = target.querySelector('textarea') as HTMLTextAreaElement;
  box.value = text;
  box.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
}

beforeEach(() => {
  vi.useFakeTimers();
  calls.length = 0;
  fake.answers = [];
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    writable: true,
    value: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  });
  reset();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  resetRightDrawerForTest();
  document.body.innerHTML = '';
  delete (globalThis as { localStorage?: unknown }).localStorage;
});

describe('the edit | preview toggle', () => {
  test('is two items, and each click draws its own body', async () => {
    const { target, app } = await drawLoaded('# head');
    const items = [...target.querySelectorAll('.oc-notes-mode [role="radio"]')] as HTMLElement[];
    expect(items.map((el) => el.dataset.notesMode)).toEqual(['edit', 'preview']);
    expect(items[0]?.getAttribute('aria-checked')).toBe('true');
    expect(target.querySelector('textarea')).not.toBeNull();

    items[1]?.click();
    flushSync();
    expect(target.querySelector('textarea')).toBeNull();
    expect(target.querySelector('[data-notes-view="preview"] h1')?.textContent).toBe('head');
    expect(items[1]?.getAttribute('aria-checked')).toBe('true');

    items[1]?.click();
    flushSync();
    expect(target.querySelector('[data-notes-view="preview"]')).not.toBeNull();

    items[0]?.click();
    flushSync();
    expect(target.querySelector('textarea')).not.toBeNull();
    expect(items[0]?.getAttribute('aria-checked')).toBe('true');
    unmount(app, { outro: false });
  });
});

describe('the save disk', () => {
  test('its color class follows each save state, and only an error prints a word', async () => {
    const { target, app } = await drawLoaded();
    const word = () => target.querySelector('.oc-notes-save-word')?.textContent ?? '';
    expect(disk(target).dataset.notesLight).toBe('saved');
    expect(word()).toBe('');

    type(target, 'start, more');
    expect(disk(target).dataset.notesLight).toBe('pending');
    expect(word()).toBe('');

    fake.answers = [new Error('network down')];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    expect(disk(target).dataset.notesLight).toBe('error');
    expect(disk(target).dataset.notesSave).toBe('failed');
    expect(word()).toBe('save failed');
    expect(disk(target).getAttribute('aria-label')).toBe('could not save');

    type(target, 'start, more, and more');
    fake.answers = [new FakeApiError('big', 413)];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    expect(disk(target).dataset.notesLight).toBe('error');
    expect(word()).toBe('too large to save');

    type(target, 'mine');
    fake.answers = [new FakeApiError('stale', 409, null, { detail: { revision: 7, body: 'theirs' } })];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    expect(disk(target).dataset.notesLight).toBe('error');
    expect(word()).toBe('save conflict');
    unmount(app, { outro: false });
  });

  test('clicking it saves now, and after a failure it retries', async () => {
    const { target, app } = await drawLoaded();
    type(target, 'typed');
    fake.answers = [new Error('network down')];
    disk(target).click();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe('PUT');
    expect(disk(target).dataset.notesLight).toBe('error');

    fake.answers = [answer('typed', 2, 'committed')];
    disk(target).click();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(calls).toHaveLength(2);
    expect(calls[1]?.body).toEqual({ body: 'typed', expected_revision: 1 });
    expect(disk(target).dataset.notesLight).toBe('saved');
    unmount(app, { outro: false });
  });
});

describe('the save disk sends one write at a time', () => {
  test('a click right after the blur it caused sends one PUT, and no conflict', async () => {
    const { target, app } = await drawDrawerLoaded();
    const box = target.querySelector('textarea') as HTMLTextAreaElement;
    box.focus();
    type(target, 'typed');
    const first = held();
    fake.answers = [first.promise];

    const press = new MouseEvent('mousedown', { bubbles: true, cancelable: true });
    disk(target).dispatchEvent(press);
    expect(press.defaultPrevented).toBe(true);
    box.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: disk(target) }));
    disk(target).click();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(puts()).toHaveLength(1);
    expect(disk(target).getAttribute('aria-busy')).toBe('true');

    first.release(answer('typed', 2, 'committed'));
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(puts()).toHaveLength(1);
    expect(target.querySelector('[data-notes-conflict]')).toBeNull();
    expect(disk(target).dataset.notesLight).toBe('saved');
    expect(disk(target).getAttribute('aria-busy')).toBe('false');
    unmount(app, { outro: false });
  });

  test('clicks during an autosave wait for it, and a later edit writes from its revision', async () => {
    const { target, app } = await drawLoaded();
    type(target, 'typed');
    const first = held();
    fake.answers = [first.promise];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    expect(puts()).toHaveLength(1);
    expect(disk(target).dataset.notesSave).toBe('saving');

    disk(target).click();
    disk(target).click();
    await vi.advanceTimersByTimeAsync(0);
    expect(puts()).toHaveLength(1);

    type(target, 'typed, more');
    disk(target).click();
    fake.answers = [answer('typed, more', 3, 'committed')];
    first.release(answer('typed', 2, 'committed'));
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(puts()).toHaveLength(2);
    expect(puts()[1]?.body).toEqual({ body: 'typed, more', expected_revision: 2 });
    expect(target.querySelector('[data-notes-conflict]')).toBeNull();
    expect(disk(target).dataset.notesLight).toBe('saved');
    unmount(app, { outro: false });
  });

  test('a click on a conflict disk sends nothing and moves focus to the two choices', async () => {
    const { target, app } = await drawLoaded();
    type(target, 'mine');
    fake.answers = [new FakeApiError('stale', 409, null, { detail: { revision: 7, body: 'theirs' } })];
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    expect(disk(target).dataset.notesLight).toBe('error');
    expect(disk(target).getAttribute('title')).toBe(
      'another computer saved this note first, choose load theirs or keep mine',
    );
    calls.length = 0;

    disk(target).click();
    await vi.advanceTimersByTimeAsync(1500);
    flushSync();
    expect(puts()).toHaveLength(0);
    const focused = document.activeElement as HTMLElement | null;
    expect(focused?.closest('[data-notes-conflict]')).not.toBeNull();
    expect(focused?.dataset.notesAction).toBeDefined();
    unmount(app, { outro: false });
  });
});

describe('the status word', () => {
  test('the status word stays a live region while empty', async () => {
    const { target, app } = await drawLoaded();
    const word = target.querySelector('.oc-notes-save-word') as HTMLElement;
    expect(word.getAttribute('role')).toBe('status');
    expect(word.textContent).toBe('');
    unmount(app, { outro: false });
  });
});

describe('one header in the right drawer', () => {
  test('the drawer head row carries the controls and the body draws none', async () => {
    const { target, app } = await drawDrawerLoaded('note');
    expect(target.querySelectorAll('[data-notes-controls]')).toHaveLength(1);
    expect(target.querySelector('[data-widget-head] [data-notes-controls]')).not.toBeNull();
    expect(target.querySelector('.nd-body [data-notes-controls]')).toBeNull();
    unmount(app, { outro: false });
  });

  test('the drawer body and the controls draw the same DOM before and after the right drawer zone (golden, wrapper Z-2)', async () => {
    const { target, app } = await drawDrawerLoaded('note');
    matchGolden('notes.drawer.body', target.querySelector('.nd-body'));
    matchGolden('notes.drawer.controls', target.querySelector('[data-notes-controls]'));
    unmount(app, { outro: false });
  });
});
