/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { flushSync, mount, unmount } from 'svelte';
import { fakeActive } from '../session-rail/test-support.svelte';
import { probed } from './placement-body-probe.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

installPopoverPolyfill();

const listing = vi.hoisted(() => ({
  data: [
    { session_row_id: 7, project_id: 4, session: { id: 'ses_1', working_dir: '/work/app' } },
    { session_row_id: 8, project_id: 5, session: { id: 'ses_2', working_dir: '/work/docs' } },
  ] as unknown[],
  status: 'ok',
}));

vi.mock('../../opscenter/api', async (importOriginal) => ({ ...(await importOriginal<Record<string, unknown>>()), sessions: listing, primarySessionId: () => 'ses_1' }));
vi.mock('../../opscenter/lib/active-terminal', async () => {
  const { fakeActive: active } = await import('../session-rail/test-support.svelte');
  return { activeTerminalSessionId: () => active.id, activeTerminalSlot: () => 'terminal:@primary' };
});
vi.mock('../../opscenter/cells/registry', async () => {
  const { PlacementProbe } = await import('./placement-body-probe.svelte');
  return { entryFor: () => ({ component: PlacementProbe }) };
});

import PlacementBody from './PlacementBody.svelte';
import { CORE_MANIFESTS } from '../../opscenter/widgets/core-manifests';
import { sessionScopeFor } from '../../opscenter/widgets/session-scope';
import { sizes } from '../../opscenter/engine/observe.svelte';
import type { BodyHost } from './host-looks';
import { HOST_LOOKS } from './host-looks';

const NOTES = CORE_MANIFESTS['core.notes']!;
const OPTIONS = { density: 'compact' };
const apps: object[] = [];

beforeEach(() => {
  fakeActive.id = 'ses_1';
  vi.stubGlobal('ResizeObserver', class { observe(): void {} unobserve(): void {} disconnect(): void {} });
  for (const host of Object.keys(HOST_LOOKS) as BodyHost[]) sizes[HOST_LOOKS[host].keyFor(NOTES, null, null)] = { width: 420, height: 400 };
});
afterEach(() => {
  while (apps.length) unmount(apps.pop()!, { outro: false });
  document.body.replaceChildren();
  for (const key of Object.keys(probed)) delete probed[key];
});

function draw(props: Record<string, unknown>): { scope: string; options: string; writes: boolean; page: string } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  apps.push(mount(PlacementBody, { target, props: { manifest: NOTES, options: OPTIONS, placementKey: 'core.notes', ...props } as never }));
  flushSync();
  const host = props['host'] as BodyHost;
  return probed[HOST_LOOKS[host].keyFor(NOTES, null, null)]!;
}

describe('one placement, three hosts', () => {
  test('a bar, the drawer area and a pop-out hand the cell the same scope and options, and all can write an option', () => {
    const store = { setOption: vi.fn(), setView: vi.fn(), resetOptions: vi.fn(), remove: vi.fn(() => true) };
    const rail = draw({ host: 'rail', source: store });
    const drawer = draw({ host: 'drawer', source: store });
    const popout = draw({ host: 'popout', placementKey: '', scope: sessionScopeFor(listing.data as never, 'ses_1') });
    for (const printed of [rail, drawer, popout]) {
      expect(printed.scope).toBe('ses_1:4');
      expect(printed.options).toBe(JSON.stringify(OPTIONS));
      expect(printed.writes).toBe(true);
    }
  });

  test('a pop-out with no session of its own gets none, not the opener\'s', () => {
    fakeActive.id = '';
    expect(draw({ host: 'popout' }).scope).toBe('none');
  });

  test('a pinned bar panel holds its agent when the selected session changes', () => {
    const pinned = draw({ host: 'rail', pinRowId: 8 });
    expect(pinned.scope).toBe('ses_2:5');
    fakeActive.id = 'ses_1';
    flushSync();
    expect(probed[HOST_LOOKS.rail.keyFor(NOTES, null, null)]!.scope).toBe('ses_2:5');
  });
});

describe('a bar section or drawer card with its header off draws no header (Joe (ccsliinc), 2026-10-23)', () => {
  const store = { setOption: vi.fn(), setView: vi.fn(), resetOptions: vi.fn(), remove: vi.fn(() => true) };

  test.each(['rail', 'drawer'] as const)('%s: only the body is drawn, focusable, and Shift+F10 opens the widget menu', (host) => {
    draw({ host, source: store, options: { show_header: false } });
    const body = document.querySelector<HTMLElement>('.pb-body')!;
    expect(document.querySelector('[data-widget-head], [data-corner], .oc-frame-corner')).toBeNull();
    expect(body.hasAttribute('data-headless')).toBe(true);
    expect(body.getAttribute('tabindex')).toBe('0');
    body.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
    flushSync();
    expect(document.querySelector('.pb-menu-spot')).not.toBeNull();
  });

  test.each(['rail', 'drawer'] as const)('%s: the headless body starts flush, with no top padding and no reserved row above it', (host) => {
    draw({ host, source: store, options: { show_header: false } });
    const body = document.querySelector<HTMLElement>('.pb-body')!;
    const source = readFileSync(resolve(process.cwd(), 'src/lib/zone-shell/PlacementBody.svelte'), 'utf8');
    const rule = /\.pb-body\[data-headless\]\s*\{([^}]*)\}/.exec(source)?.[1] ?? '';
    expect(rule).toContain('border');
    expect(rule).not.toMatch(/padding(-top|-block(-start)?)?\s*:/);
    expect(body.previousElementSibling).toBeNull();
  });

  test('a pop-out has no tick, so its body is not made focusable', () => {
    draw({ host: 'popout', placementKey: '', scope: sessionScopeFor(listing.data as never, 'ses_1') });
    expect(document.querySelector('.pb-body')!.hasAttribute('tabindex')).toBe(false);
  });
});
