/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';

import CellFrame from './CellFrame.svelte';
import { META, metaFor } from '../engine/meta';
import { homeLayout } from '../engine/layout.svelte';
import { layoutEditor } from '../layout-editor/editor.svelte';
import type { SlotId } from '../engine/types';
import { installPopoverPolyfill } from '../../lib/popover-jsdom-polyfill';

installPopoverPolyfill();

let app: object | null = null;

beforeEach(() => {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
});

afterEach(() => {
  if (app) unmount(app as never);
  app = null;
  layoutEditor.active = false;
  layoutEditor.page = null;
  document.body.innerHTML = '';
});

function frame(): { wrap: HTMLElement; button: HTMLElement } {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const slot = 'stat-running' as SlotId;
  app = mount(CellFrame, {
    target,
    props: {
      meta: metaFor(slot, META),
      instance: slot,
      widthState: '',
      heightState: '',
      store: homeLayout,
      body: createRawSnippet(() => ({ render: () => '<p>tile</p>' })),
    },
  });
  flushSync();
  const button = target.querySelector<HTMLElement>('.oc-frame-corner')!;
  return { wrap: button.parentElement!, button };
}

test('in edit layout the gear moves to the top right slot, boxless and not accent-coloured inline', () => {
  const normal = frame();
  expect(normal.wrap.style.left).toBe('8px');
  expect(normal.wrap.style.right).toBe('');
  expect(normal.button.hasAttribute('data-edit-gear')).toBe(false);
  unmount(app as never);
  document.body.innerHTML = '';

  layoutEditor.active = true;
  layoutEditor.page = homeLayout.page;
  const editing = frame();
  expect(editing.button.hasAttribute('data-edit-gear')).toBe(true);
  expect(editing.wrap.style.right).toBe('8px');
  expect(editing.wrap.style.left).toBe('');
  expect(editing.button.querySelector('svg')).not.toBeNull();
  expect(editing.button.style.color).toBe('');
});
