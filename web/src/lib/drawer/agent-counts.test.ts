import { expect, test } from 'vitest';
import { countAgents, rowCountsAs } from './agent-counts';

const c = (rows: Record<string, unknown>[]) => countAgents(rows.map((r, i) => ({ name: `r${i}`, ...r })) as never);

test('working and working_subagent are active and working; idle is active only', () => {
  expect(c([{ status: 'working' }, { status: 'working_subagent' }, { status: 'idle' }])).toMatchObject({ active: 3, working: 2, unread: 0 });
});

test('question, notice, startup gate and unknown count as active, not working', () => {
  expect(c([{ status: 'question' }, { status: 'notice' }, { status: 'unknown' }, { status: 'idle', startup_gate: 'trust' }]))
    .toMatchObject({ active: 4, working: 0 });
});

test('dead and asleep rows are not active; unread counts on dead but not on asleep', () => {
  expect(c([{ status: 'dead', unread: true }, { status: 'asleep', asleep: true, unread: true }, { status: 'idle', archived: true, unread: true }]))
    .toMatchObject({ active: 0, working: 0, unread: 1 });
});

test('browser, layout and shell rows are not agents', () => {
  expect(c([{ status: 'working', kind: 'browser' }, { status: 'working', kind: 'layout' }, { status: 'working', agent_family: 'shell' }]))
    .toMatchObject({ active: 0, working: 0 });
});

test('a paired computer counts while up; one that is not up is left out and named', () => {
  const out = c([
    { status: 'working', host_state: 'up', host_label: 'studio' },
    { status: 'working', host_state: 'down', host_label: 'mini' },
    { status: 'idle', unread: true, host_state: 'degraded', host_label: 'mini' },
  ]);
  expect(out).toMatchObject({ active: 1, working: 1, unread: 0 });
  expect(out.offline).toEqual(['mini']);
});

test('the nested session.unread is never read', () => {
  expect(c([{ status: 'idle', session: { unread: true } }]).unread).toBe(0);
});

test('rowCountsAs is the rule behind each figure, so a filter lists exactly the rows its number counted', () => {
  const rows = [
    { name: 'a', status: 'working' }, { name: 'b', status: 'idle', unread: true }, { name: 'c', status: 'dead', unread: true },
    { name: 'd', status: 'asleep', asleep: true }, { name: 'e', status: 'working', host_state: 'down' },
  ];
  const listed = (kind: 'active' | 'working' | 'unread'): string[] => rows.filter((r) => rowCountsAs(r, kind)).map((r) => r.name);
  const counts = countAgents(rows);
  expect(listed('active')).toEqual(['a', 'b']);
  expect(listed('working')).toEqual(['a']);
  expect(listed('unread')).toEqual(['b', 'c']);
  expect([listed('active').length, listed('working').length, listed('unread').length]).toEqual([counts.active, counts.working, counts.unread]);
});
