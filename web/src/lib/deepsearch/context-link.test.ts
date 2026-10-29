import { expect, test } from 'vitest';
import { LINK_PREFIX, linkHash, parseLink } from './context-link';

test('a link round-trips, with a subagent file and a paired computer', () => {
  const plain = { conversationId: 'c-1', line: 7, fileKind: 'conversation' as const, hostKey: null };
  expect(linkHash(plain)).toBe('#deepsearch/context?c=c-1&l=7');
  expect(parseLink(linkHash(plain))).toEqual(plain);
  const far = { conversationId: 'c 2/x', line: 0, fileKind: 'subagent' as const, hostKey: 'peer-hostb' };
  expect(parseLink(linkHash(far))).toEqual(far);
  expect(linkHash({ ...plain, hostKey: 'local' })).not.toContain('h=');
});

test('a hash that is not a link, or is malformed, opens nothing', () => {
  for (const bad of ['', '#', '#projects/3', `${LINK_PREFIX}`, `${LINK_PREFIX}?c=x`, `${LINK_PREFIX}?l=3`, `${LINK_PREFIX}?c=x&l=-1`, `${LINK_PREFIX}?c=x&l=abc`, `${LINK_PREFIX}?c=x&l=1.5`]) {
    expect(parseLink(bad), bad).toBeNull();
  }
});
