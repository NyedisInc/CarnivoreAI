/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import TabbedFrame from '../../shell/fixtures/TabbedFrame.svelte';
import { resetTabCache } from '../../engine/tab-groups.svelte';
import { inputFocus } from '../../lib/input-focus.svelte';
import type { SlotId } from '../../engine/types';
import { fakeRail, THREE } from '../../../lib/terminal-search/prompt-header-harness';
import { noteConnection, transportFor } from './connection.svelte';
import { INNER_LABELS } from '../../../lib/led';

const search = vi.hoisted(() => ({ current: null as unknown }));

vi.mock('./client', () => ({ startLiveTerminal: () => null }));
vi.mock('./actions', () => ({
  registerTerminalActions: () => () => {}, terminalAction: vi.fn(), toolShowing: () => false,
}));
vi.mock('./theme', () => ({ bindTerminalTheme: () => () => {} }));
vi.mock('../../../lib/terminal-search/cell-search', () => ({
  cellSearchFor: () => search.current,
}));
vi.mock('../../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api')>();
  return {
    ...actual,
    sessions: {
      data: [{
        session: { id: 'ses_a' }, label: 'alpha', agent_family: 'claude', tmux_session: 'cloude_ses_a',
        activity_status: 'working_subagent', startup_gate: null, unread: false, pinned_theme: null,
      }],
      status: 'ok', refresh: vi.fn(), fetchedAt: 1, error: null, stop() {},
    },
  };
});

const A = 'terminal:ses_a' as SlotId;
let app: ReturnType<typeof mount> | null = null;
let hosted: { rail: ReturnType<typeof fakeRail>['rail']; headerHosted: boolean; focusTerminal(): void };

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {} unobserve(): void {} disconnect(): void {}
  };
  resetTabCache();
  const { rail } = fakeRail(THREE);
  hosted = { rail, headerHosted: false, focusTerminal: () => {} };
  search.current = hosted;
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  hosted.rail.dispose();
  noteConnection('ses_a', null);
  inputFocus.forget(A);
  resetTabCache();
  document.body.replaceChildren();
  localStorage.clear();
});

function draw(width = 1200): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(TabbedFrame, { target, props: { slot: A, width } });
  flushSync();
  hosted.rail.setViewport(100);
  flushSync();
  return target;
}

test('the tabbed row carries no status line and no connected, and is the prompt bar: text then arrows; the icon group is in the strip, not here (#627)', () => {
  const root = draw();
  const title = root.querySelector('.oc-frame-title') as HTMLElement;
  expect(title.querySelector('.oc-tl-status')).toBeNull();
  expect(title.textContent).not.toContain('working');
  expect(title.querySelector('.oc-connection')).toBeNull();
  const bar = title.querySelector('.prompt-header-root--inline') as HTMLElement;
  expect(bar).not.toBeNull();
  expect(bar.hidden).toBe(false);
  expect(hosted.headerHosted).toBe(true);
  const order = [
    title.querySelector('.prompt-header__preview'),
    title.querySelector('[data-prompt-key="prev"]'),
    title.querySelector('[data-prompt-key="next"]'),
  ];
  for (const el of order) expect(el).not.toBeNull();
  for (let i = 1; i < order.length; i += 1) {
    const follows = order[i - 1]!.compareDocumentPosition(order[i]!) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(follows).toBeTruthy();
  }
  expect(title.querySelector('.prompt-header__preview')?.textContent).toContain('first line');
  expect(root.querySelector('.oc-tl-gap')).not.toBeNull();
  const strip = root.querySelector('.oc-frame-strip') as HTMLElement;
  expect(title.querySelector('.oc-tl-controls')).toBeNull();
  expect(strip.querySelector('.oc-tl-controls')).not.toBeNull();
});

test('every icon keeps its accessible name, and a narrow component folds them into the kebab; the icons live in the strip (#627)', () => {
  let root = draw(1200);
  let strip = root.querySelector('.oc-frame-strip') as HTMLElement;
  expect(strip.querySelector('.cell-tools [data-tool="search"]')).not.toBeNull();
  for (const button of strip.querySelectorAll('.cell-tools button')) {
    expect(button.getAttribute('aria-label')).toBeTruthy();
  }
  void unmount(app!);
  app = null;
  document.body.replaceChildren();
  root = draw(240);
  strip = root.querySelector('.oc-frame-strip') as HTMLElement;
  const kebab = strip.querySelector('[data-tool="overflow"]') as HTMLButtonElement;
  expect(kebab).not.toBeNull();
  expect(kebab.getAttribute('aria-haspopup')).toBe('menu');
  expect(strip.querySelector('.cell-tools [data-tool="search"]')).toBeNull();
  expect(strip.querySelector('.cell-options [role="menuitem"][data-tool="search"]')).not.toBeNull();
  const title = root.querySelector('.oc-frame-title') as HTMLElement;
  expect(title.querySelector('.prompt-header__preview')).not.toBeNull();
});

test('the inline bar is collapsed by default, and the toggle grows only itself (O23)', () => {
  const root = draw();
  const title = root.querySelector('.oc-frame-title') as HTMLElement;
  const bar = title.querySelector('.prompt-header') as HTMLElement;
  const more = title.querySelector('[data-prompt-key="more"]') as HTMLButtonElement;
  expect(bar.className).not.toContain('prompt-header--expanded');
  expect(more.getAttribute('aria-expanded')).toBe('false');

  more.click();
  flushSync();
  expect(bar.className).toContain('prompt-header--expanded');
  expect(more.getAttribute('aria-expanded')).toBe('true');
  const order = [
    title.querySelector('.prompt-header__preview'),
    title.querySelector('[data-prompt-key="prev"]'),
    title.querySelector('[data-prompt-key="next"]'),
  ];
  for (const el of order) expect(el).not.toBeNull();
  for (let i = 1; i < order.length; i += 1) {
    const follows = order[i - 1]!.compareDocumentPosition(order[i]!) & Node.DOCUMENT_POSITION_FOLLOWING;
    expect(follows).toBeTruthy();
  }
  expect(title.querySelectorAll('.prompt-header-root').length).toBe(1);
  expect(root.querySelector('.oc-frame-strip .oc-tl-controls')).not.toBeNull();

  more.click();
  flushSync();
  expect(bar.className).not.toContain('prompt-header--expanded');
  expect(more.getAttribute('aria-expanded')).toBe('false');
});

test('a dropped socket reddens the tab light and names the drop on the tab; back up clears it', () => {
  const root = draw();
  const tab = () => root.querySelector('[role="tab"]') as HTMLElement;
  noteConnection('ses_a', { text: 'Disconnected', className: 'error' });
  flushSync();
  expect(tab().querySelector('.status-led')?.getAttribute('data-inner')).toBe('disconnected');
  expect(tab().hasAttribute('title')).toBe(false);
  noteConnection('ses_a', { text: 'Reconnecting...', className: '' });
  expect(transportFor('ses_a')).toBe('disconnected');
  noteConnection('ses_a', { text: 'Connected', className: 'connected' });
  flushSync();
  expect(tab().querySelector('.status-led')?.getAttribute('data-inner')).not.toBe('disconnected');
  expect(tab().hasAttribute('title')).toBe(false);
});
