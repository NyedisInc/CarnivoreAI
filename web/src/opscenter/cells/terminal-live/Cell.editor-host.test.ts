/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Cell from './Cell.svelte';
import { metaFor } from '../../engine/meta';
import type { SlotId } from '../../engine/types';

const registered: { container: HTMLElement; overlay: HTMLElement | null | undefined; client: unknown }[] = [];
const started: HTMLElement[] = [];

vi.mock('./client', () => ({
  startLiveTerminal: (host: HTMLElement) => {
    started.push(host);
    return { client: { fake: true }, dispose(): void {} };
  },
}));
vi.mock('./actions', () => ({
  registerTerminalActions: (
    _slot: string, client: unknown, container: HTMLElement, _primary?: boolean, overlay?: HTMLElement | null,
  ) => {
    registered.push({ container, overlay, client });
    return () => {};
  },
  terminalAction: vi.fn(),
  toolShowing: () => false,
}));
vi.mock('./theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      data: [{
        session: { id: 'ses_e' }, tmux_session: 'carnivore_e', label: 'a session',
        pinned_theme: null, activity_status: 'idle', startup_gate: null, unread: false,
      }],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const component of mounted.splice(0)) await unmount(component);
  document.body.replaceChildren();
  registered.length = 0;
  started.length = 0;
});

test('the overlay handed to the files action is the body around the pane, not the pane', () => {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(Cell, {
    target,
    props: { width: 900, height: 400, meta: metaFor('terminal:ses_e' as SlotId), instance: 'terminal:ses_e' },
  }));
  flushSync();

  expect(started).toHaveLength(1);
  expect(registered).toHaveLength(1);
  const { container, overlay } = registered[0]!;
  expect(container).toBe(started[0]);
  expect(overlay).not.toBe(container);
  expect(overlay).toBe(container.parentElement);
  expect(overlay?.classList.contains('oc-tl-body')).toBe(true);
});
