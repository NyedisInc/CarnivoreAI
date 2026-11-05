/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import WidgetHead from './WidgetHead.svelte';
import TerminalFrame from './fixtures/TerminalFrame.svelte';
import { createFrameHeader } from './frame-header.svelte';
import { META, TERMINAL_META, metaFor } from '../engine/meta';
import type { SlotId } from '../engine/types';

vi.mock('../../opscenter/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  sessions: { data: [{ session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/work/app' } }], status: 'ok' },
  primarySessionId: () => 'ses_1',
}));
vi.mock('../../opscenter/lib/active-terminal', () => ({ activeTerminalSessionId: () => 'ses_1', activeTerminalSlot: () => 'terminal:@primary' }));
vi.mock('../../opscenter/cells/registry', async () => {
  const { PlacementProbe } = await import('../../lib/zone-shell/placement-body-probe.svelte');
  return { entryFor: () => ({ component: PlacementProbe }) };
});

import PlacementBody from '../../lib/zone-shell/PlacementBody.svelte';
import { CORE_MANIFESTS } from '../widgets/core-manifests';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

let app: object | null = null;
let target: HTMLElement;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
  target = document.createElement('div');
  document.body.appendChild(target);
});

afterEach(async () => {
  if (app) await unmount(app);
  app = null;
  target.remove();
});

function head(locked: boolean): HTMLElement {
  const meta = metaFor('running-sessions' as SlotId, META);
  app = mount(WidgetHead, {
    target,
    props: {
      meta,
      header: createFrameHeader('running-sessions'),
      title: 'sessions',
      corner: createRawSnippet(() => ({ render: () => '<button type="button" data-corner>m</button>' })),
      onClose: () => {},
      withRight: false,
      locked,
    },
  });
  flushSync();
  return target.querySelector<HTMLElement>('[data-widget-head]')!;
}

describe('the lock mark', () => {
  test('a locked header wears the lock next to the title, labeled; an unlocked one does not', () => {
    const locked = head(true);
    const mark = locked.querySelector<HTMLElement>('[data-head-lock]');
    expect(mark).not.toBeNull();
    expect(mark!.getAttribute('aria-label')).toBeTruthy();
    expect(mark!.nextElementSibling?.tagName).toBe('H2');
    expect(mark!.querySelector('svg')).not.toBeNull();
  });

  test('an unlocked header draws no lock', async () => {
    expect(head(false).querySelector('[data-head-lock]')).toBeNull();
  });

  test('the mark takes its color from the declared token, never a literal', () => {
    const source = readFileSync(join(__dirname, 'HeadLockMark.svelte'), 'utf8');
    expect(source).toMatch(/\.oc-head-lock\s*{[^}]*color:\s*var\(--oc-locked\)/);
    expect(source).toMatch(/\.oc-head-lock\s*{[^}]*font-size:\s*var\(--oc-fs-title\)/);
    expect(source).toMatch(/\.oc-head-lock :global\(svg\)\s*{[^}]*width:\s*1em/);
    const tokens = readFileSync(join(__dirname, '..', 'tokens.css'), 'utf8');
    expect(tokens.match(/--oc-locked:/g)?.length).toBeGreaterThanOrEqual(2);
    expect(tokens).toMatch(/\[data-theme="dracula"\][^}]*--oc-locked:/);
  });
});

describe('the divider before close', () => {
  test('a cell that fills the content slot still gets the hairline before its close x', () => {
    const meta = metaFor('running-sessions' as SlotId, META);
    const header = createFrameHeader('running-sessions');
    header.content = createRawSnippet(() => ({ render: () => '<span data-own>own head</span>' }));
    app = mount(WidgetHead, { target, props: { meta, header, title: 'sessions', corner: null, onClose: () => {}, withRight: false } });
    flushSync();
    const close = target.querySelector('[data-head-close]');
    expect(close!.previousElementSibling?.getAttribute('role')).toBe('separator');
  });

  test('a closable header with no controls still draws the hairline before the close x', () => {
    const row = head(false);
    const close = row.querySelector('[data-head-close]');
    expect(close).not.toBeNull();
    expect(close!.previousElementSibling?.getAttribute('role')).toBe('separator');
  });
});

describe('the terminal head', () => {
  test('below 1024 a terminal never folds: no accordion button, the row keeps its controls', () => {
    const header = createFrameHeader('terminal:@primary');
    header.action = createRawSnippet(() => ({ render: () => '<span data-tool>tool</span>' }));
    app = mount(WidgetHead, {
      target,
      props: { meta: TERMINAL_META, header, title: 'alpha', corner: null, onClose: null, withRight: false, phone: true },
    });
    flushSync();
    expect(target.querySelector('.oc-frame-toggle')).toBeNull();
    expect(target.querySelector('[aria-expanded]')).toBeNull();
    expect(target.querySelector('h2.oc-frame-name')?.textContent).toBe('alpha');
    expect(target.querySelector('[data-tool]')).not.toBeNull();
  });

  test('an untabbed terminal fills the standard row: the standard name and the standard cluster', () => {
    app = mount(TerminalFrame, { target });
    flushSync();
    const row = target.querySelector<HTMLElement>('[data-widget-head]')!;
    expect(row.querySelector('h2.oc-frame-name')?.textContent).toBe('alpha');
    expect(row.querySelector('.oc-frame-spacer')).not.toBeNull();
    expect(row.querySelector('.oc-head-group [data-terminal-header]')).not.toBeNull();
    expect(row.querySelector('.oc-tl-name')).toBeNull();
    expect(row.querySelector('[role="status"]')).not.toBeNull();
  });
});

function drawerHead(widgetId: string, placement: string | null, pinned: boolean): string[] {
  const store = { setOption: vi.fn(), setView: vi.fn(), resetOptions: vi.fn(), remove: vi.fn(() => true) };
  app = mount(PlacementBody, {
    target,
    props: {
      host: 'drawer', manifest: CORE_MANIFESTS[widgetId]!, target: placement, source: store, placementKey: widgetId,
      pinRowId: pinned ? 7 : null, options: {},
    } as never,
  });
  flushSync();
  const row = document.querySelector<HTMLElement>('[data-widget-head]')!;
  const close = row.querySelector('[data-head-close]');
  return [
    row.querySelector('h2.oc-frame-name') ? 'title' : 'no-title',
    close?.previousElementSibling?.getAttribute('role') === 'separator' ? 'divider' : 'no-divider',
    close ? 'close' : 'no-close',
    row.querySelector('[data-head-lock]') ? 'lock' : 'no-lock',
  ];
}

describe('a drawer-placed terminal wears the same head as a drawer-placed notes widget', () => {
  test.each([[false], [true]])('locked=%s: title, divider, close and lock match', async (pinned) => {
    const notes = drawerHead('core.notes', null, pinned);
    await unmount(app!);
    app = null;
    document.body.querySelectorAll('[data-widget-head]').forEach((one) => one.remove());
    const terminal = drawerHead('core.terminal', 'row:7', pinned);
    expect(terminal).toEqual(notes);
    expect(notes).toEqual(['title', 'divider', 'close', pinned ? 'lock' : 'no-lock']);
  });
});
