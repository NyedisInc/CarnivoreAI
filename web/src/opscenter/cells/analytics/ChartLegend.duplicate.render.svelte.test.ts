/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ChartLegend from './ChartLegend.svelte';

afterEach(() => { document.body.innerHTML = ''; vi.unstubAllGlobals(); });

test('two items with the same name render as two entries without throwing', () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
  const target = document.createElement('div');
  document.body.append(target);
  const app = mount(ChartLegend, { target, props: { onToggle: () => {}, items: [
    { id: '0:tokens:a:after', name: 'helper', color: 'red', on: true }, { id: '0:tokens:b:after', name: 'helper', color: 'blue', on: true } ] } });
  flushSync();
  expect(target.querySelectorAll('.chart-legend__item').length).toBe(2);
  unmount(app);
});
