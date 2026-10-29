import { afterEach, expect, test, vi } from 'vitest';

import { twoFrames } from './two-frames';

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test('resolves on the timer when animation frames never fire', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('requestAnimationFrame', () => 0);
  let done = false;
  void twoFrames(50).then(() => (done = true));
  await vi.advanceTimersByTimeAsync(60);
  expect(done).toBe(true);
});

test('resolves after two frames when frames fire', async () => {
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => setTimeout(() => cb(0), 0));
  await expect(twoFrames(5000)).resolves.toBeUndefined();
});
