import { expect, test } from 'vitest';
import { statusLabel } from './sessions.svelte';

test('question hint words a question, permission keeps its wording', () => {
  expect(statusLabel('question', null, null, null, 'question')).toBe('your turn - question waiting');
  expect(statusLabel('question', null, null, null, 'question:2/3')).toBe(
    'your turn - question 2 of 3 waiting',
  );
  expect(statusLabel('question', null, null, null, null)).toBe(
    'your turn - the agent needs your permission',
  );
  expect(statusLabel('working', null, null, null, 'question')).toBe('working');
});
