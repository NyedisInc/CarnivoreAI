/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import WidgetAreaBar from './WidgetAreaBar.svelte';
import { WIDGET_AREA_STORAGE_KEY } from './widget-area.svelte';
import type { WidgetAreaState } from './types';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  document.body.innerHTML = '';
  localStorage.clear();
});

function bar(state: WidgetAreaState, seen: WidgetAreaState[]): HTMLElement {
  const target = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(WidgetAreaBar, { target, props: { state, onchange: (next: WidgetAreaState) => seen.push(next), area: () => null } }));
  return target.querySelector<HTMLElement>('[data-area-bar]')!;
}

const key = async (node: HTMLElement, name: string) => {
  node.dispatchEvent(new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true }));
  await tick();
  flushSync();
};

describe('WidgetAreaBar, controlled', () => {
  it('shows the given state and asks for one step per Up or Down, never past an end', async () => {
    const seen: WidgetAreaState[] = [];
    const node = bar('glance', seen);
    expect(node.getAttribute('data-area-state')).toBe('glance');
    await key(node, 'ArrowDown');
    await key(node, 'ArrowUp');
    expect(seen).toEqual(['closed', 'full']);
    const top: WidgetAreaState[] = [];
    await key(bar('full', top), 'ArrowUp');
    expect(top.every((next) => next === 'full')).toBe(true);
  });

  it('Enter closes a full area and opens a closed one, and writes nothing to the per-tab store', async () => {
    const seen: WidgetAreaState[] = [];
    await key(bar('full', seen), 'Enter');
    const shut: WidgetAreaState[] = [];
    await key(bar('closed', shut), ' ');
    expect(seen).toEqual(['closed']);
    expect(shut).toEqual(['full']);
    expect(localStorage.getItem(WIDGET_AREA_STORAGE_KEY)).toBeNull();
  });

  it('a click on a closed bar asks for full', async () => {
    const seen: WidgetAreaState[] = [];
    const node = bar('closed', seen);
    node.click();
    await tick();
    expect(seen).toEqual(['full']);
  });
});
