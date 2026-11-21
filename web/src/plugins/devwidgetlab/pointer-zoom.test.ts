/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { ancestorZoom, counterZoom } from './pointer-zoom';

test('ancestor zooms multiply and the counter-zoom is the inverse', () => {
  const outer = document.createElement('div');
  const inner = document.createElement('div');
  const leaf = document.createElement('span');
  inner.append(leaf);
  outer.append(inner);
  document.body.append(outer);
  const zooms = new Map<Element, string>([[outer, '0.5'], [inner, '0.8']]);
  const factor = ancestorZoom(leaf, (node) => ({ zoom: zooms.get(node) ?? 'normal' }));
  expect(factor).toBeCloseTo(0.4);
  expect(counterZoom(factor)).toBeCloseTo(2.5);
  expect(counterZoom(1)).toBeNull();
  outer.remove();
});
