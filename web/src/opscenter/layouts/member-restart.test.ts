import { expect, test } from 'vitest';
import { memberRestartRequest } from './member-restart';

test('a dead-pane member (picker mode restart) posts to respawn by tmux name, never recreate', () => {
  const r = memberRestartRequest({ mode: 'restart', agentType: null }, 'u1', 'carnivore_x');
  expect(r.path).toBe('/sessions/respawn');
  expect(r.body).toEqual({ session_name: 'carnivore_x' });
  expect(r.kind).toBe('restart');
});

test('a gone member (picker mode recreate) posts to recreate by uuid with its wrapper', () => {
  const r = memberRestartRequest({ mode: 'recreate', agentType: 'claude', sessionUuid: 'u2' }, 'u1', 't');
  expect(r.path).toBe('/sessions/recreate');
  expect(r.body).toEqual({ session_uuid: 'u2', agent_type: 'claude' });
});
