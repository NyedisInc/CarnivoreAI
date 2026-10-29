import { describe, expect, test } from 'vitest';
import { moveTargets } from './huddle-model';

describe('the move menu targets', () => {
  test('an agent thread is not a target; shared and projects are', () => {
    const lists = [{ key: 'all' }, { key: '12' }, { key: '18' }, { key: 'agent:5' }];
    expect(moveTargets(lists, '12').map((r) => r.key)).toEqual(['all', '18']);
  });
});
