import { expect, test } from 'vitest';
import { stateKindOf } from './state-kind';

test('a failed read is the error kind, a read in flight the loading kind, everything else the plain empty kind', () => {
  expect(stateKindOf('error')).toBe('error');
  expect(stateKindOf('loading')).toBe('loading');
  for (const quiet of ['signed-out', 'unavailable', 'ok', undefined, '']) expect(stateKindOf(quiet)).toBe('empty');
});
