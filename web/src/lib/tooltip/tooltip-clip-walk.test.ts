/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { tooltipTargetFor } from './tooltip';

test('a carrier with a hundred descendants is measured at most about forty times', () => {
  document.body.innerHTML = `<button title="alpha">alpha${'<i>x</i>'.repeat(100)}</button>`;
  const carrier = document.body.firstElementChild as Element;
  let measured = 0;
  for (const box of carrier.querySelectorAll('i')) {
    Object.defineProperty(box, 'scrollWidth', { get: () => { measured += 1; return 0; } });
  }
  expect(tooltipTargetFor(carrier)).toBeNull();
  expect(measured).toBeGreaterThan(0);
  expect(measured).toBeLessThanOrEqual(40);
});
