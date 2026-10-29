/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import App from './App.svelte';
import { viewport } from './engine/viewport.svelte';

(globalThis as { ResizeObserver?: unknown }).ResizeObserver ??= class {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
};

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

function renderAt(width: number): HTMLElement {
  viewport.wide = width >= 1024;
  viewport.phone = width < 701;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(App, { target }));
  flushSync();
  return target;
}

for (const width of [1440, 390]) {
  test(`at ${width} the home screen draws no rail and the surface fills the shell`, () => {
    const root = renderAt(width);
    const shell = root.querySelector('.oc-app');
    expect(shell, 'the home screen did not mount').not.toBeNull();
    expect(root.querySelector('nav'), 'a navigation landmark is drawn on the home screen').toBeNull();
    expect(root.querySelector('.oc-sidebar, .oc-nav')).toBeNull();
    expect(root.querySelector('.oc-content')?.parentElement).toBe(shell);
  });
}
