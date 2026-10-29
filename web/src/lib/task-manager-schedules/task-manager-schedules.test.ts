import { expect, test } from 'vitest';
import { taskManagerSchedules } from './task-manager-scheduled';

const wire = (item: number, over: Record<string, unknown> = {}) => ({
  list: '12', item, title: `t${item}`, next_fire: '2026-10-12T15:00:00-04:00', paused: false, state: 'pending', pings: { session_key: 'u-1' }, ...over,
});

test('rows keep the server order and carry the session key; a sent one-shot is left out; a paused repeat stays, off', () => {
  const rows = taskManagerSchedules({ schedules: [wire(1), wire(2, { state: 'fired', next_fire: null }), wire(3, { paused: true, state: 'paused' }), wire(4, { pings: { session_key: null } })] });
  expect(rows.map((r) => [r.item, r.sessionKey, r.paused])).toEqual([[1, 'u-1', false], [3, 'u-1', true], [4, null, false]]);
  expect(rows[0]!.fireAt).toBe(Date.parse('2026-10-12T15:00:00-04:00') / 1000);
});

test('no body, no rows', () => {
  expect(taskManagerSchedules(null)).toEqual([]);
  expect(taskManagerSchedules({})).toEqual([]);
});
