/** @vitest-environment jsdom */
import { expect, test } from 'vitest';
import { railKeyTarget } from './rail-keys.svelte';

test('railKeyTarget: Up/Down and Left/Right walk with wrap, Home and End jump, anything else is not ours', () => {
  const ids = ['a', 'b', 'c'];
  expect(railKeyTarget('ArrowDown', ids, 'a')).toBe('b');
  expect(railKeyTarget('ArrowRight', ids, 'c')).toBe('a');
  expect(railKeyTarget('ArrowUp', ids, 'a')).toBe('c');
  expect(railKeyTarget('ArrowLeft', ids, 'b')).toBe('a');
  expect(railKeyTarget('Home', ids, 'c')).toBe('a');
  expect(railKeyTarget('End', ids, 'a')).toBe('c');
  expect(railKeyTarget('Enter', ids, 'a')).toBeNull();
  expect(railKeyTarget('ArrowDown', [], null)).toBeNull();
  expect(railKeyTarget('ArrowDown', ids, 'gone'), 'a focus we do not know starts at the first').toBe('a');
});
