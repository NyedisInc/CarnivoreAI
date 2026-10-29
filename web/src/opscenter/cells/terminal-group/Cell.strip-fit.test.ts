/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { META, metaFor } from '../../engine/meta';
import { sizes } from '../../engine/observe.svelte';
import { resetTabCache } from '../../engine/tab-groups.svelte';
import { fitsForSlot, SIZE_UNIT_PX } from '../../widgets/fits';
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
        session: { id: 'ses_a' }, label: 'alpha', agent_family: 'claude', tmux_session: 'cloude_ses_a',
        activity_status: 'idle', startup_gate: null, unread: false, pinned_theme: null,
      }],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_a' as SlotId;
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

test('a body that fits only with the strip counted mounts once, keeps its strip and draws no refusal plate', () => {
  const fits = fitsForSlot(A);
  expect(fits, 'the terminal declares a fit contract, or this measured nothing').not.toBeNull();
  const stripPx = metaFor(A, META).titleHeight;
  const floorEdgePx = (fits!.min.h - 0.5) * SIZE_UNIT_PX.h;
  const bodyPx = Math.floor(floorEdgePx - stripPx / 2);
  expect(Math.round(bodyPx / SIZE_UNIT_PX.h)).toBeLessThan(fits!.min.h);
  expect(Math.round((bodyPx + stripPx) / SIZE_UNIT_PX.h)).toBeGreaterThanOrEqual(fits!.min.h);
  sizes[A] = { width: 1200, height: bodyPx };

  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A } });
  flushSync();

  expect(target.querySelector('.oc-frame-strip [role="tab"]')).not.toBeNull();
  expect(target.querySelector('[data-widget-unavailable]')).toBeNull();
});
