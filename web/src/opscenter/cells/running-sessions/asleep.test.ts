import { describe, expect, test } from 'vitest';
import { asleepRows, isAsleepRow, ASLEEP_KEY_PREFIX } from './asleep';
import type { SessionRecord } from '../../api/types';

function rec(over: Partial<SessionRecord> = {}): SessionRecord {
  return {
    session_uuid: 'u-a',
    origin: 'created',
    owned: true,
    lifecycle: 'stopped',
    title: 'fix the deploy',
    working_dir: '/w',
    agent_type: 'claude',
    agent_family: 'claude',
    archived_at: null,
    created_at: '2026-09-25T10:00:00Z',
    last_work_at: null,
    project_id: 3,
    tmux_name: 'carnivore_a',
    asleep: true,
    ...over,
  };
}

describe('asleep sessions in the running table (issue #537)', () => {
  test('an asleep record becomes a row keyed apart from every live id, with nothing measured', () => {
    const row = asleepRows([rec()], new Set())[0]!;
    expect(isAsleepRow(row)).toBe(true);
    expect(row.session.id).toBe(`${ASLEEP_KEY_PREFIX}u-a`);
    expect(row.session_uuid).toBe('u-a');
    expect(row.label).toBe('fix the deploy');
    expect(row.tmux_session).toBe('carnivore_a');
    expect(row.activity_status).toBeNull();
    expect(row.status_source).toBeNull();
    expect(row.unread).toBe(false);
  });

  test('a record flagged for follow-up carries it onto the row (issue #749)', () => {
    expect(asleepRows([rec({ unread: true })], new Set())[0]!.unread).toBe(true);
    expect(asleepRows([rec({ unread: null })], new Set())[0]!.unread).toBe(false);
  });

  test('a live row holding the name, a deleted record, a waking one and a nameless one add nothing', () => {
    expect(asleepRows([rec()], new Set(['carnivore_a']))).toEqual([]);
    expect(asleepRows([rec({ archived_at: '2026-09-01T00:00:00Z' })], new Set())).toEqual([]);
    expect(asleepRows([rec({ asleep: false })], new Set())).toEqual([]);
    expect(asleepRows([rec({ tmux_name: null })], new Set())).toEqual([]);
    expect(asleepRows([rec()], new Set(['carnivore_b']))).toHaveLength(1);
  });

  test('a live row is never read as asleep', () => {
    const live = { ...asleepRows([rec()], new Set())[0]!, asleep: undefined };
    expect(isAsleepRow(live as never)).toBe(false);
  });
});
