import { expect, test } from 'vitest';
import { hueDotToken, hueLabelToken } from './status-hue-tokens';

test('every hue maps to a token, grey to the dim text, dot one shade brighter where one exists', () => {
  expect(hueDotToken('green')).toBe('var(--oc-green-bright)');
  expect(hueLabelToken('green')).toBe('var(--oc-green)');
  expect(hueDotToken('yellow')).toBe('var(--oc-yellow-bright)');
  expect(hueLabelToken('yellow')).toBe('var(--oc-yellow)');
  for (const f of [hueDotToken, hueLabelToken]) {
    expect(f('blue')).toBe('var(--oc-cyan)');
    expect(f('red')).toBe('var(--oc-coral)');
    expect(f('grey')).toBe('var(--oc-text-dim)');
  }
});
