import type { SessionInfo, SessionRecord } from '../../../api/types';

export const listing = $state<{ sessions: SessionInfo[] | null; asleep: SessionRecord[] | null }>({
  sessions: null,
  asleep: [],
});
