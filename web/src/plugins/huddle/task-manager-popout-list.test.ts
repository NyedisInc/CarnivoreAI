import { expect, test } from 'vitest';
import { firstPopoutList, popoutListKey, rememberPopoutList } from './task-manager-popout-list';

function windowStorage(): Storage {
  const map = new Map<string, string>();
  return { getItem: (k: string) => map.get(k) ?? null, setItem: (k: string, v: string) => void map.set(k, v) } as unknown as Storage;
}

test('two pop-outs keep separate list choices and neither follows the other', () => {
  const a = windowStorage();
  const b = windowStorage();
  expect(firstPopoutList(a, 'w-a', '?tab=huddle&list=18')).toBe('18');
  expect(firstPopoutList(b, 'w-b', '?tab=huddle&list=aggregate')).toBe('aggregate');
  rememberPopoutList(a, 'w-a', '22');
  rememberPopoutList(b, 'w-b', 'aggregate');
  expect(firstPopoutList(a, 'w-a', '?tab=huddle&list=18')).toBe('22');
  expect(firstPopoutList(b, 'w-b', '?tab=huddle&list=18')).toBe('aggregate');
});

test('window names key the storage apart and a bad stored value falls back to the URL', () => {
  expect(popoutListKey('x')).not.toBe(popoutListKey('y'));
  const s = windowStorage();
  s.setItem(popoutListKey('w'), 'not a list');
  expect(firstPopoutList(s, 'w', '?list=7')).toBe('7');
  expect(firstPopoutList(null, 'w', '')).toBeNull();
});
