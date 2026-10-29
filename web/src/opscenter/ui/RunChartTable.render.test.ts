/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import RunChartTableProbe from './fixtures/RunChartTableProbe.svelte';

const rows = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
let app: Record<string, unknown> | null = null;

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
});

test('draws one cell per row, capped by limit, and all of them with no limit', () => {
  app = mount(RunChartTableProbe, { target: document.body, props: { rows, limit: 2, phone: false } });
  flushSync();
  expect(document.querySelectorAll('[data-probe-cell]').length).toBe(2);
  unmount(app);
  app = mount(RunChartTableProbe, { target: document.body, props: { rows, limit: null, phone: true } });
  flushSync();
  expect(document.querySelectorAll('[data-probe-cell]').length).toBe(3);
});
