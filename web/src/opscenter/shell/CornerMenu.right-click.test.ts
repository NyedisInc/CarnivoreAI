/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import CellFrame from './CellFrame.svelte';
import { META, metaFor } from '../engine/meta';
import { homeLayout, terminalLayout } from '../engine/layout.svelte';
import type { SlotId } from '../engine/types';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

let app: object | null = null;

function frame(slot: SlotId): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  app = mount(CellFrame, {
    target,
    props: {
      meta: metaFor(slot, META),
      instance: slot,
      widthState: '',
      heightState: '',
      store: homeLayout,
      body: createRawSnippet(() => ({ render: () => '<p>body</p>' })),
    },
  });
  flushSync();
  return target;
}

/** A right-click on an element the way the page receives it. Inputs: el. Output: the event. */
function rightClick(el: Element): MouseEvent {
  const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 });
  el.dispatchEvent(event);
  flushSync();
  return event;
}

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  homeLayout.resetAll();
  terminalLayout.resetAll();
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('the title strip icon', () => {
  test('a right-click on it opens the widget menu in place of the browser\'s', () => {
    const root = frame('running-sessions' as SlotId);
    const icon = root.querySelector<HTMLButtonElement>('.oc-frame-corner')!;
    expect(icon).not.toBeNull();
    expect(document.querySelector('.acm-menu')).toBeNull();
    const event = rightClick(icon);
    expect(event.defaultPrevented).toBe(true);
    expect(document.querySelector('.acm-menu')).not.toBeNull();
  });

  test('the focused icon takes the same event (Shift+F10 in a browser)', () => {
    const icon = frame('running-sessions' as SlotId).querySelector<HTMLButtonElement>('.oc-frame-corner')!;
    icon.focus();
    expect(document.activeElement).toBe(icon);
    rightClick(document.activeElement!);
    expect(document.querySelector('.acm-menu')).not.toBeNull();
  });
});
