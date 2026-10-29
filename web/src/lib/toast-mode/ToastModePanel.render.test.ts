/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ToastModePanel from './ToastModePanel.svelte';

type G = { PreferenceBridge?: unknown };

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  delete (globalThis as G).PreferenceBridge;
});

function install(answer: unknown = { status: 'committed' }) {
  const state = { stored: undefined as unknown, writes: [] as unknown[], follow: null as null | ((v: unknown) => void) };
  (globalThis as G).PreferenceBridge = {
    read: (_f: string, local: () => unknown) => (state.stored !== undefined ? state.stored : local()),
    write: async (_f: string, value: unknown) => {
      state.writes.push(value);
      const ok = (answer as { status: string }).status === 'committed';
      if (ok) state.stored = value;
      return answer;
    },
    follow: (_f: string, apply: (v: unknown) => void) => {
      state.follow = apply;
      return () => { state.follow = null; };
    },
  };
  return state;
}

function render(): HTMLElement {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ToastModePanel, { target }));
  flushSync();
  return target;
}

const radio = (root: HTMLElement, mode: string) =>
  root.querySelector(`input[data-toast-mode="${mode}"]`) as HTMLInputElement;

async function settle(): Promise<void> {
  for (let i = 0; i < 5; i += 1) { await tick(); await Promise.resolve(); }
  flushSync();
}

test('compact is checked when nothing is stored', () => {
  install();
  const root = render();
  expect(radio(root, 'compact').checked).toBe(true);
  expect(radio(root, 'detailed').checked).toBe(false);
});

test('picking detailed saves it once', async () => {
  const state = install();
  const root = render();
  radio(root, 'detailed').click();
  await settle();
  expect(state.writes).toEqual(['detailed']);
  expect(radio(root, 'detailed').checked).toBe(true);
  expect(root.querySelector('[role="alert"]')).toBeNull();
});

test('a refused save puts compact back and says why', async () => {
  const state = install({ status: 'refused', detail: 'not read yet' });
  const root = render();
  radio(root, 'detailed').click();
  await settle();
  expect(state.writes).toEqual(['detailed']);
  expect(radio(root, 'compact').checked).toBe(true);
  expect(root.querySelector('[role="alert"]')?.textContent).toContain('not read yet');
});

test('a change from another device moves the checked row', async () => {
  const state = install();
  const root = render();
  expect(state.follow).not.toBeNull();
  state.follow!('detailed');
  await settle();
  expect(radio(root, 'detailed').checked).toBe(true);
});
