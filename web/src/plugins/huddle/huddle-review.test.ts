import { describe, expect, test } from 'vitest';
import { isStatusEcho } from './huddle-review';

describe('isStatusEcho', () => {
  test('answer and read only restate the status; the other actions and free words stay', () => {
    expect(['answer', 'read', 'push', 'tick', 'pick one', null].map(isStatusEcho)).toEqual([true, true, false, false, false, false]);
  });
});
