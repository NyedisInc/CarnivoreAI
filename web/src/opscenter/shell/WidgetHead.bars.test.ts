/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount, type Component } from 'svelte';

vi.mock('../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../api/auth.svelte')>();
  return { ...real, authFetch: async () => ({ threads: [], next_before: null }) };
});

import CellInFrame from './fixtures/CellInFrame.svelte';
import TimelineCell from '../cells/timeline/Cell.svelte';
import CrosstalkCell from '../cells/crosstalk/Cell.svelte';
import { homeLayout } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import type { CellProps } from '../lib/cell';
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

afterEach(() => {
  if (app) unmount(app);
  app = null;
  for (const id of ['timeline', 'crosstalk'] as SlotId[]) homeLayout.setHeaderShown(id, true);
  document.body.replaceChildren();
});

function inFrame(slot: string, cell: Component<CellProps>): void {
  app = mount(CellInFrame, { target, props: { slot: slot as SlotId, cell } });
  flushSync();
}

const head = (): HTMLElement | null => target.querySelector<HTMLElement>('[data-widget-head]');

describe('the bars a cell hands up', () => {
  test('the timeline picker sits in the header, separated from the close x; ticked off, the row and the picker stay put', () => {
    inFrame('timeline', TimelineCell as Component<CellProps>);
    expect(head()!.querySelector('[data-facet="timeline-session"]')).not.toBeNull();
    expect(head()!.querySelectorAll('.oc-head-sep').length).toBeGreaterThanOrEqual(1);
    expect(target.querySelector('.oc-tl-top')).toBeNull();
    homeLayout.setHeaderShown('timeline' as SlotId, false);
    flushSync();
    expect(head()!.classList.contains('oc-frame-title--bare')).toBe(true);
    expect(head()!.querySelector('[data-facet="timeline-session"]')).not.toBeNull();
    expect(target.querySelector('.oc-tl-top')).toBeNull();
  });

  test('the crosstalk switch is in neither the header nor the body, header ticked on or off', () => {
    inFrame('crosstalk', CrosstalkCell as Component<CellProps>);
    expect(target.querySelector('[data-crosstalk-scope]')).toBeNull();
    homeLayout.setHeaderShown('crosstalk' as SlotId, false);
    flushSync();
    expect(target.querySelector('[data-crosstalk-scope]')).toBeNull();
    expect(target.querySelector('[data-widget-note]')).not.toBeNull();
  });
});
