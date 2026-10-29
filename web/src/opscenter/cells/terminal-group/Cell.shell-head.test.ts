/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { sizes } from '../../engine/observe.svelte';
import { resetTabCache } from '../../engine/tab-groups.svelte';
import type { SlotId } from '../../engine/types';
import { installPopoverPolyfill } from '../../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

vi.mock('../terminal-live/client', () => ({ startLiveTerminal: () => null }));
vi.mock('../terminal-live/actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('../terminal-live/theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      data: [{
        session: { id: 'ses_sh' }, label: 'M4 Terminal', agent_family: 'shell', tmux_session: 'carnivore_console-1',
        activity_status: null, startup_gate: null, unread: false, pinned_theme: null,
      }],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_sh' as SlotId;
let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  delete sizes[A];
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
});

test('a shell terminal under its tab strip has no empty title row', () => {
  sizes[A] = { width: 636, height: 600 };
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A, width: 636 } });
  flushSync();

  expect(target.querySelector('.oc-frame-strip [role="tab"]'), 'the strip drew, or this measured nothing').not.toBeNull();
  expect(target.querySelector('.oc-frame-title')?.outerHTML ?? null).toBeNull();
  const frame = target.querySelector<HTMLElement>('.oc-frame');
  const rows = frame?.style.gridTemplateRows ?? '';
  expect(rows.match(/var\(--oc-titlerow\)/g)?.length ?? 0, `grid rows: ${rows}`).toBe(1);
});
