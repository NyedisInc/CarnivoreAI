import { describe, expect, test } from 'vitest';
import { isMenuKey, nextKey } from './key-nav';

const ids = ['a', 'b', 'c'];

describe('nextKey', () => {
  test('a bar key strip (ZoneKeys): its own axis only, Home and End jump, the ends stay put', () => {
    expect(nextKey('ArrowDown', ids, 'a', 'y', false)).toBe('b');
    expect(nextKey('ArrowUp', ids, 'b', 'y', false)).toBe('a');
    expect(nextKey('ArrowDown', ids, 'c', 'y', false), 'the end of the strip stays put').toBeNull();
    expect(nextKey('ArrowUp', ids, 'a', 'y', false)).toBeNull();
    expect(nextKey('ArrowRight', ids, 'a', 'y', false), 'the cross axis is not the strip\'s').toBeNull();
    expect(nextKey('ArrowRight', ids, 'a', 'x', false)).toBe('b');
    expect(nextKey('ArrowDown', ids, 'a', 'x', false)).toBeNull();
    expect(nextKey('Home', ids, 'c', 'x', false)).toBe('a');
    expect(nextKey('End', ids, 'a', 'y', false)).toBe('c');
  });

  test('the left rail (railKeyTarget): both axes, wrapping, an unknown focus starts at the first', () => {
    expect(nextKey('ArrowDown', ids, 'c', 'both', true)).toBe('a');
    expect(nextKey('ArrowRight', ids, 'a', 'both', true)).toBe('b');
    expect(nextKey('ArrowUp', ids, 'a', 'both', true)).toBe('c');
    expect(nextKey('ArrowLeft', ids, 'b', 'both', true)).toBe('a');
    expect(nextKey('ArrowDown', ids, 'gone', 'both', true)).toBe('a');
    expect(nextKey('ArrowUp', ids, null, 'both', true)).toBe('a');
  });

  test('the main tab strip (TabStrip): along x, wrapping both ways', () => {
    expect(nextKey('ArrowRight', ids, 'c', 'x', true)).toBe('a');
    expect(nextKey('ArrowLeft', ids, 'a', 'x', true)).toBe('c');
    expect(nextKey('ArrowUp', ids, 'b', 'x', true)).toBeNull();
  });

  test('anything else is not a navigation key, and an empty strip has nowhere to go', () => {
    expect(nextKey('Enter', ids, 'a', 'both', true)).toBeNull();
    expect(nextKey('Delete', ids, 'a', 'x', true)).toBeNull();
    expect(nextKey('Home', [], null, 'x', true)).toBeNull();
    expect(nextKey('ArrowDown', [], null, 'y', false)).toBeNull();
  });
});

test('isMenuKey: the menu key and Shift+F10, nothing else', () => {
  expect(isMenuKey({ key: 'ContextMenu', shiftKey: false })).toBe(true);
  expect(isMenuKey({ key: 'F10', shiftKey: true })).toBe(true);
  expect(isMenuKey({ key: 'F10', shiftKey: false })).toBe(false);
  expect(isMenuKey({ key: 'Enter', shiftKey: true })).toBe(false);
});
