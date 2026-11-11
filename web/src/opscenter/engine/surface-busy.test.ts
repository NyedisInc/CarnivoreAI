import { expect, test } from 'vitest';
import { registerBusy, surfaceBusy } from './surface-busy';

test('a registered motion handle holds the syncs while busy and releases on unregister', () => {
  let busy = false;
  const off = registerBusy(() => busy);
  expect(surfaceBusy()).toBe(false);
  busy = true;
  expect(surfaceBusy()).toBe(true);
  busy = false;
  expect(surfaceBusy()).toBe(false);
  busy = true;
  off();
  expect(surfaceBusy()).toBe(false);
});
