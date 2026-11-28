import { beforeEach, describe, expect, test, vi } from 'vitest';

const authFetch = vi.fn();
vi.mock('../sdk', () => ({
  authFetch: (...a: unknown[]) => authFetch(...a),
  resourcePush: () => ({ onChange: () => {} }),
  familyOf: (t: string) => t,
  t: (key: string) => ({
    'cplug.huddle.role.lead_on': 'make project lead', 'cplug.huddle.role.lead_off': 'stop being project lead',
  } as Record<string, string>)[key] ?? key,
}));

import { swarmRoster } from './agents/agent-roster.svelte';
import { refreshSessionNudge, resetSessionNudge } from './task-manager-session-prefs';
import { roleActions } from './session-roles-action';

const lead = roleActions[0]!;
const row = { name: 'cloude_a', unread: false, sessionId: 'ses_1', sessionUuid: 'u-1', projectId: 7 };
const refresh = vi.fn();

beforeEach(async () => {
  authFetch.mockReset();
  refresh.mockReset();
  resetSessionNudge();
  swarmRoster.agents = [];
  authFetch.mockResolvedValueOnce({ sessions: {}, lists: {}, leads: {}, dnd: [] });
  await refreshSessionNudge();
  authFetch.mockReset();
});

describe('labels', () => {
  test('lead toggles on the seat', async () => {
    expect(lead.payload.label(row)).toBe('make project lead');
    authFetch.mockResolvedValueOnce({ sessions: {}, lists: {}, leads: { '7': 'u-1' }, dnd: ['u-1'] });
    await refreshSessionNudge();
    expect(lead.payload.label(row)).toBe('stop being project lead');
  });
});

describe('runs', () => {
  test('make lead PUTs the seat, then the label flips', async () => {
    authFetch.mockResolvedValueOnce({ list: '7', seat: {} });
    await lead.payload.run(row, { flags: {}, refresh });
    expect(authFetch).toHaveBeenCalledWith('/cplugs/huddle/lists/7/lead', { method: 'PUT', body: JSON.stringify({ session: 'u-1' }) });
    expect(lead.payload.label(row)).toBe('stop being project lead');
    expect(refresh).toHaveBeenCalled();
  });

  test('stop leading clears the seat with null', async () => {
    authFetch.mockResolvedValueOnce({}).mockResolvedValueOnce({});
    await lead.payload.run(row, { flags: {}, refresh });
    await lead.payload.run(row, { flags: {}, refresh });
    expect(authFetch).toHaveBeenLastCalledWith('/cplugs/huddle/lists/7/lead', { method: 'PUT', body: JSON.stringify({ session: null }) });
  });
});

describe('withheld', () => {
  test('a Swarm agent body hides the lead item', () => {
    swarmRoster.agents = [{ id: 1, session_id: 'ses_1' } as never];
    expect(lead.payload.hidden?.(row)).toBe(true);
  });

  test('an ordinary session shows it; no project hides it', () => {
    expect(lead.payload.hidden?.(row)).toBe(false);
    expect(lead.payload.hidden?.({ ...row, projectId: null })).toBe(true);
  });

  test('do not disturb is no row item any more (#2604)', () => {
    expect(roleActions.map((a) => a.id)).toEqual(['huddle-project-lead']);
  });
});
