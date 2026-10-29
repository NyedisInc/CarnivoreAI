import { expect, test } from 'vitest';
import { splitFoot, FOOT_STEPS } from './foot-toolbar';

test('the four non-core steps sit at 440 / 520 / 1080 / 1320, narrowest first', () => {
  expect(FOOT_STEPS.map((s) => [s.name, s.min])).toEqual([
    ['core', 0],
    ['bars', 440],
    ['effort', 520],
    ['tokens', 1080],
    ['reset', 1320],
  ]);
});

test('below 440px, nothing beyond the core set (labels, model name, percents) is admitted', () => {
  const split = splitFoot(300);
  expect(split).toMatchObject({ bars: false, effort: true, tokens: false, reset: false });
});

test('a width comfortably above every step admits everything at once', () => {
  const split = splitFoot(2560);
  expect(split).toMatchObject({ bars: true, effort: true, tokens: true, reset: true });
});

test('FootSplit no longer carries account, accountShort or cost flags', () => {
  const split = splitFoot(2560) as unknown as Record<string, unknown>;
  expect(split.account).toBeUndefined();
  expect(split.accountShort).toBeUndefined();
  expect(split.cost).toBeUndefined();
});
