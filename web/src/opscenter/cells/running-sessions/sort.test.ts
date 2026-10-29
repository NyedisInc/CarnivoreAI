import { describe, expect, test } from 'vitest';

import { SORT_KEYS, statusPriority, sortRows } from './sort.svelte';
import type { SessionInfo } from '../../api';

function row(opts: {
  id: string;
  label?: string;
  activity_status?: string | null;
  unread?: boolean | null;
  startup_gate?: string | null;
  workingDir?: string;
  lastActivity?: string;
}): SessionInfo {
  return {
    session: {
      id: opts.id,
      pty_pid: null,
      working_dir: opts.workingDir ?? '~/dev/x',
      status: 'running',
      created_at: '2026-09-25T00:00:00',
      last_activity: opts.lastActivity ?? '2026-09-25T00:00:00',
      agent_type: null,
      pinned_theme: null,
      tmux_session: null,
      model: null,
    },
    recent_logs: [],
    stats: { total_commands: 0, uptime_seconds: 0, log_lines: 0, local_servers: 0 },
    session_backend: 'tmux',
    tmux_session: null,
    label: opts.label ?? opts.id,
    agent_type: null,
    agent_family: null,
    agent_family_source: null,
    agent_wrapper_label: null,
    pinned_theme: null,
    activity_status: opts.activity_status ?? null,
    activity_hint: null,
    unread: opts.unread ?? null,
    startup_gate: opts.startup_gate ?? null,
    status_source: null,
  };
}

describe('SORT_KEYS', () => {
  test('is exactly the four orderings, activity first as the default', () => {
    expect(SORT_KEYS).toEqual(['activity', 'name', 'last_used', 'project']);
  });
});

describe('statusPriority: the five-hue urgency model, restated as a number', () => {
  test('working beats a live question beats notice beats finished-unread beats idle beats unknown beats dead', () => {
    const working = statusPriority(row({ id: 'w', activity_status: 'working' }));
    const question = statusPriority(row({ id: 'q', activity_status: 'question' }));
    const notice = statusPriority(row({ id: 'n', activity_status: 'notice' }));
    const finishedUnread = statusPriority(row({ id: 'f', activity_status: 'idle', unread: true }));
    const idle = statusPriority(row({ id: 'i', activity_status: 'idle' }));
    const unknown = statusPriority(row({ id: 'u' }));
    const dead = statusPriority(row({ id: 'd', activity_status: 'dead' }));
    expect(working).toBeLessThan(question);
    expect(question).toBeLessThan(notice);
    expect(notice).toBeLessThan(finishedUnread);
    expect(finishedUnread).toBeLessThan(idle);
    expect(idle).toBeLessThan(unknown);
    expect(unknown).toBeLessThan(dead);
  });

  test('the startup gate outranks a missing activity_status the same way statusHue treats it', () => {
    const gated = statusPriority(row({ id: 'g', startup_gate: 'awaiting_startup_prompt' }));
    const unknown = statusPriority(row({ id: 'u' }));
    expect(gated).toBeLessThan(unknown);
  });
});

describe('sortRows', () => {
  const now = Date.parse('2026-09-25T12:00:00Z');
  const rows: SessionInfo[] = [
    row({ id: 'a', label: 'charlie', activity_status: 'idle', lastActivity: '2026-09-25T11:00:00' }),
    row({ id: 'b', label: 'alpha', activity_status: 'working', lastActivity: '2026-09-25T11:50:00' }),
    row({ id: 'c', label: 'bravo', activity_status: 'question', lastActivity: '2026-09-25T11:55:00' }),
  ];

  test('activity: status priority first, most-recently-active breaks a tie', () => {
    const ordered = sortRows(rows, 'activity', [], now);
    expect(ordered.map((r) => r.session.id)).toEqual(['b', 'c', 'a']);
  });

  test('name: alphabetical by the same label the NAME column prints', () => {
    const ordered = sortRows(rows, 'name', [], now);
    expect(ordered.map((r) => r.label)).toEqual(['alpha', 'bravo', 'charlie']);
  });

  test('last_used: most recently active first, regardless of status', () => {
    const ordered = sortRows(rows, 'last_used', [], now);
    expect(ordered.map((r) => r.session.id)).toEqual(['c', 'b', 'a']);
  });

  test('never mutates the array it was handed', () => {
    const original = rows.slice();
    sortRows(rows, 'name', [], now);
    expect(rows).toEqual(original);
  });
});
