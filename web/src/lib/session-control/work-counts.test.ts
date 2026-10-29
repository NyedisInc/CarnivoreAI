import { expect, test } from 'vitest';
import type { SessionBackgroundWork, BackgroundProcess } from '../background-work/background-work';
import type { SubagentRow } from '../subagents/subagents';
import { workCounts } from './control-center';

const agent = (id: string, status: SubagentRow['status']): SubagentRow => ({
  id, agent_type: 'Explore', description: id, model: null, background: true, spawn_depth: 1,
  started_at: '2026-10-15T10:00:00Z', last_activity_at: null, status, status_reason: 'x', end_status: null,
}) as SubagentRow;

const proc = (pid: number, agentId: string | null): BackgroundProcess => ({
  pid, start: `s${pid}`, task_id: null, started_at: null, children: 0, summary: null, agent_id: agentId,
});

const rows = [agent('a1', 'running'), agent('a2', 'running'), agent('a3', 'running'), agent('a4', 'running'),
  agent('done-owner', 'done'), agent('done-idle', 'done')];
const work = (processes: BackgroundProcess[], state: SessionBackgroundWork['state'] = 'ok'): SessionBackgroundWork => ({
  state, family: 'claude', processes, owners: 'ok', detail: '', as_of: null,
});
const seven = [1, 2, 3, 4, 5, 6].map((n) => proc(n, n === 6 ? 'done-owner' : null)).concat(proc(7, 'a1'));

test('agents are the running listed sub-agents, shells every row of the process list', () => {
  expect(workCounts(rows, work(seven))).toEqual({ agents: 4, shells: 7 });
});

test('the old summed listing fields cannot produce these counts', () => {
  const listing = { subagents_running: 2, background_open: 2 };
  const counts = workCounts(rows, work(seven));
  expect(counts.shells).not.toBe(listing.subagents_running + listing.background_open);
});

test('null is not zero: unread or unmeasured lists give null', () => {
  expect(workCounts(null, null)).toEqual({ agents: null, shells: null });
  expect(workCounts(rows, work([], 'unchecked'))).toEqual({ agents: 4, shells: null });
  expect(workCounts([], work([]))).toEqual({ agents: 0, shells: 0 });
});
