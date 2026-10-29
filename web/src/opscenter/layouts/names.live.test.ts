/** @vitest-environment jsdom */
import { expect, test, vi } from 'vitest';

const listing = vi.hoisted(() => ({
  data: [
    { session: { id: 's-a' }, session_row_id: 1, activity_status: 'dead' },
    { session: { id: 's-b' }, session_row_id: 2, activity_status: 'working' },
  ] as unknown[],
  status: 'ok',
  refresh: async () => undefined,
}));
vi.mock('../api/sessions.svelte', () => ({ sessions: listing }));

import { isLiveRow, liveMemberRowFor } from './names';
import type { SessionInfo } from '../api/types';

test('a dead pane is listed but not live', () => {
  expect(isLiveRow(listing.data[0] as SessionInfo)).toBe(false);
  expect(isLiveRow(listing.data[1] as SessionInfo)).toBe(true);
  expect(isLiveRow(null)).toBe(false);
});

test('liveMemberRowFor skips a dead husk and an absent row', () => {
  expect(liveMemberRowFor(1)).toBeNull();
  expect(liveMemberRowFor(2)?.session_row_id).toBe(2);
  expect(liveMemberRowFor(9)).toBeNull();
  expect(liveMemberRowFor(null)).toBeNull();
});
