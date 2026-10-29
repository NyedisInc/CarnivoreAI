import type { Mark, SessionTimeline } from './types';

export function markOf(fields: Partial<Mark> & Pick<Mark, 'id' | 'kind' | 'conversation_id'>): Mark {
  return {
    at: null, entry_uuid: null, label: '', snippet: '', can_peek: false, trigger: null, pre_tokens: null, bookmark_id: null,
    created_by: null, point_id: null, reason: null, pinned: null, failsafe: null, turns: null, ...fields,
  };
}

export function timelineFixture(): SessionTimeline {
  return {
    session_uuid: 'row-uuid-1', session_row_id: 7, family: 'claude', current_conversation: 'conv-c', now: '2026-10-10T13:00:00Z',
    bars: [
      { conversation_id: 'conv-a', current: false, level: 'human', began: null, started_at: '2026-10-10T10:00:00Z', ended_at: '2026-10-10T11:00:00Z' },
      { conversation_id: 'conv-b', current: false, level: 'human', started_at: '2026-10-10T11:00:00Z', ended_at: '2026-10-10T12:00:00Z',
        began: { kind: 'clear', from_conversation: 'conv-a', basis: 'recorded', at: '2026-10-10T11:00:00Z', split: null } },
      { conversation_id: 'conv-c', current: true, level: 'human', started_at: '2026-10-10T12:00:00Z', ended_at: '2026-10-10T13:00:00Z',
        began: { kind: 'rewind', from_conversation: 'conv-b', basis: 'recorded', at: '2026-10-10T12:00:00Z',
          split: { conversation: 'conv-b', message_uuid: 'm7', line: null, at: '2026-10-10T11:40:00Z' } } },
    ],
    marks: [
      markOf({ id: 'restart:conv-a:1', kind: 'restart', conversation_id: 'conv-a', at: '2026-10-10T10:20:00Z' }),
      markOf({ id: 'compact:conv-b:9', kind: 'compact', conversation_id: 'conv-b', at: '2026-10-10T11:20:00Z', entry_uuid: 'cb', can_peek: true, trigger: 'auto', pre_tokens: 90000 }),
      markOf({ id: 'restore:conv-b:20261010T112500Z-kill', kind: 'restore', conversation_id: 'conv-b', at: '2026-10-10T11:25:00Z', point_id: '20261010T112500Z-kill', reason: 'kill', pinned: false, failsafe: false, turns: 14, snippet: 'ship it' }),
      markOf({ id: 'bookmark:1', kind: 'bookmark', conversation_id: 'conv-c', at: '2026-10-10T12:10:00Z', entry_uuid: 'u2', can_peek: true, label: 'the second ask', bookmark_id: 1, created_by: 'owner', snippet: 'second prompt' }),
      markOf({ id: 'restart:conv-c:2', kind: 'restart', conversation_id: 'conv-c', at: '2026-10-10T12:20:00Z' }),
    ],
    gaps: [
      { id: 'sleep:conv-a:1', conversation_id: 'conv-a', start: '2026-10-10T10:30:00Z', end: '2026-10-10T10:45:00Z', open: false },
      { id: 'sleep:conv-c:2', conversation_id: 'conv-c', start: '2026-10-10T12:40:00Z', end: null, open: true },
    ],
  };
}
