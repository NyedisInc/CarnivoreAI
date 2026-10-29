/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';

vi.mock('../api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/auth.svelte')>()),
  authFetch: vi.fn(async () => ({ values: {} })),
}));
vi.mock('../../lib/help/feature-media', () => ({
  fetchFeatureMediaBlob: () => Promise.reject(new Error('no server in this test')),
}));

import { HOME_LAYOUT_FIELD as FIELD, WRITE_DELAY, resetHomeSync, startHomeSync, type HomeValue } from '../engine/home-sync.svelte';
import { homeLayout } from '../engine/layout.svelte';
import { resetLayout } from '../engine/model';
import { META } from '../engine/meta';
import { flushSave } from '../engine/persist';
import { unmountPanel } from '../../lib/mount';
import { editorSeams, enterLayoutEditor, finishLayoutEditor, layoutEditor } from './editor.svelte';
import { POPOUT_EDITOR_HOST_ID, startPopoutEditor } from './popout-editor';

const real = { ...editorSeams };
const sets: unknown[] = [];

const held: HomeValue = {
  v: 2,
  boards: [
    { id: 'home', name: 'home', layout: resetLayout(META, 'home') },
    { id: 'b-2', name: 'second', layout: resetLayout(META, 'home') },
  ],
  analytics_seed: 2,
  active: 'home',
};

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  sets.length = 0;
  (globalThis as { Preferences?: unknown }).Preferences = {
    HYDRATED: 'hydrated',
    COMMITTED: 'committed',
    status: () => 'hydrated',
    committedValue: (name: string) => (name === FIELD ? held : undefined),
    set: async (_name: string, value: unknown) => {
      sets.push(value);
      return { status: 'committed' };
    },
    subscribe: () => () => {},
  };
  const screen = document.createElement('div');
  screen.id = 'popout-screen';
  document.body.appendChild(screen);
});

afterEach(() => {
  if (layoutEditor.active) finishLayoutEditor();
  unmountPanel(POPOUT_EDITOR_HOST_ID);
  resetHomeSync();
  flushSave();
  Object.assign(editorSeams, real);
  delete (globalThis as { Preferences?: unknown }).Preferences;
  document.body.replaceChildren();
  localStorage.clear();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

test('a dashboard pop-out adds a widget from its drawer and saves only its own board, through its route', async () => {
  const { authFetch } = await import('../api/auth.svelte');
  const fetch = authFetch as unknown as ReturnType<typeof vi.fn>;
  fetch.mockResolvedValue({ values: { [FIELD]: held } });
  startHomeSync({ target: null, popout: true, board: 'b-2', edit: true });
  await vi.advanceTimersByTimeAsync(10);

  expect(startPopoutEditor()).toBe(true);
  flushSync();
  expect(document.querySelector('.le-drawer')).toBeNull();

  expect(enterLayoutEditor()).toBe(true);
  flushSync();
  const drawer = document.querySelector<HTMLElement>('.le-drawer')!;
  expect(drawer).not.toBeNull();
  expect(drawer.classList.contains('le-drawer--docked')).toBe(false);
  expect(drawer.querySelector('[data-zone-shelf]')).toBeNull();
  expect(drawer.querySelector('[data-zone-card]')).toBeNull();

  const notes = drawer.querySelector<HTMLButtonElement>('[data-le-card][data-widget="core.notes"]')!;
  expect(notes.dataset['state']).toBe('addable');
  notes.click();
  await vi.advanceTimersByTimeAsync(10);
  flushSync();
  const slots = (): string[] => homeLayout.state.layout.rows.flatMap((row) => row.slots.map((slot) => slot.id));
  expect(slots()).toContain('notes');

  drawer.querySelector<HTMLButtonElement>('[data-layout-editor-done]')!.click();
  flushSync();
  expect(layoutEditor.active).toBe(false);
  await vi.advanceTimersByTimeAsync(WRITE_DELAY * 6);

  const puts = fetch.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'PUT');
  expect(puts.length).toBeGreaterThan(0);
  const last = puts[puts.length - 1]!;
  expect(last[0]).toBe('/dashboards/b-2/layout');
  const saved = JSON.parse(String((last[1] as RequestInit).body)).layout as { rows: { slots: { id: string }[] }[] };
  expect(saved.rows.flatMap((row) => row.slots.map((slot) => slot.id))).toContain('notes');
  expect(sets).toHaveLength(0);
});
