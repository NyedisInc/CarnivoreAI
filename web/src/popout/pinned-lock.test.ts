/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../opscenter/api', () => ({
  isDemo: () => false,
  auth: { state: 'signed-in' },
  initAuth: () => {},
  startEvents: () => {},
  sessions: { status: 'idle', data: null },
  transport: { state: 'unknown' },
}));

import SingleWidget from './SingleWidget.svelte';
import { placementFromSearch, widgetPath, type PopoutPlacement } from './popout';
import { popOutFor } from '../lib/zone-shell/pop-out';
import { CORE_MANIFESTS } from '../opscenter/widgets/core-manifests';
import { installPopoverPolyfill } from '../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

let app: ReturnType<typeof mount> | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

function lockShown(placement: PopoutPlacement): boolean {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(SingleWidget, { target, props: { widget: 'core.tasks', placement } });
  flushSync();
  return target.querySelector('[data-widget-head] [data-head-lock]') !== null;
}

describe('the pop-out lock', () => {
  test('pinned plus the session view shows the lock; pinned on the all sessions view shows none; unpinned shows none', () => {
    expect(lockShown({ sessionId: 'ses_1', view: 'session', pinned: true })).toBe(true);
    unmount(app!);
    app = null;
    document.body.innerHTML = '';
    expect(lockShown({ sessionId: 'ses_1', view: 'all', pinned: true })).toBe(false);
    unmount(app!);
    app = null;
    document.body.innerHTML = '';
    expect(lockShown({ sessionId: 'ses_1', view: 'session' })).toBe(false);
  });

  test('the pinned fact rides the URL and the pop out action: a pinned tab sets it, an unpinned one does not', () => {
    const path = widgetPath('core.tasks', { sessionId: 'ses_1', view: 'session', pinned: true });
    expect(placementFromSearch(path.slice(path.indexOf('?')))).toMatchObject({ pinned: true });
    expect(widgetPath('core.tasks', { sessionId: 'ses_1' })).not.toContain('pinned');
    const open = vi.spyOn(window, 'open').mockReturnValue(null);
    const tasks = CORE_MANIFESTS['core.tasks']!;
    popOutFor(tasks, tasks, 'session', { sessionId: 'ses_1', projectId: 4 }, undefined, true)?.();
    popOutFor(tasks, tasks, 'session', { sessionId: 'ses_1', projectId: 4 }, undefined)?.();
    const urls = open.mock.calls.map((call) => String(call[0]));
    expect(urls[0]).toContain('pinned=1');
    expect(urls[1]).not.toContain('pinned');
  });
});
