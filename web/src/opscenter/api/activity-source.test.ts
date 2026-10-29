import { expect, test, vi } from 'vitest';
import type { SessionInfo } from './types';

const sessionRows: SessionInfo[] = [];

vi.mock('./sessions.svelte', () => ({
  sessions: {
    get data() {
      return sessionRows;
    },
  },
}));

const { sourceForHandle } = await import('./activity.svelte');

function row(id: string, tmuxSession: string, label: string | null): SessionInfo {
  return {
    session: { id } as SessionInfo['session'],
    recent_logs: [],
    stats: {} as SessionInfo['stats'],
    session_backend: 'tmux',
    tmux_session: tmuxSession,
    label,
    agent_type: null,
    agent_family: null,
    agent_family_source: null,
    agent_wrapper_label: null,
    pinned_theme: null,
    activity_status: null,
    activity_hint: null,
    unread: null,
    startup_gate: null,
    status_source: null,
  };
}

test('a loaded row with a label wins over its tmux name', () => {
  sessionRows.splice(0, sessionRows.length, row('s1', 'cloude_api', 'billing api'));
  expect(sourceForHandle('cloude_api')).toBe('billing api');
});

test('a loaded row with no label falls back to its own tmux name', () => {
  sessionRows.splice(0, sessionRows.length, row('s1', 'cloude_api', null));
  expect(sourceForHandle('cloude_api')).toBe('cloude_api');
});

test('a loaded row is matched by session id too, not only tmux name', () => {
  sessionRows.splice(0, sessionRows.length, row('s1', 'cloude_api', 'billing api'));
  expect(sourceForHandle('s1')).toBe('billing api');
});

test('no loaded row for the handle: the cloude_-stripped handle, not the raw slug', () => {
  sessionRows.splice(0, sessionRows.length);
  expect(sourceForHandle('cloude_orphan')).toBe('orphan');
});

test('an external (non-cloude) handle with no loaded row renders verbatim', () => {
  sessionRows.splice(0, sessionRows.length);
  expect(sourceForHandle('carnivore_Agent_-_Cloude_Code')).toBe('carnivore_Agent_-_Cloude_Code');
});

test('no handle at all is the empty string, never a dash or a label', () => {
  sessionRows.splice(0, sessionRows.length);
  expect(sourceForHandle(null)).toBe('');
  expect(sourceForHandle(undefined)).toBe('');
  expect(sourceForHandle('')).toBe('');
});
