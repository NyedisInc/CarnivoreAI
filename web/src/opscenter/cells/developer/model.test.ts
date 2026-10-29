import { describe, expect, test } from 'vitest';
import { automationArea, byWords, resultOf, SCHEDULED_COLUMNS, scheduledChart } from './model';
import { columnsFor, nextWords } from '../../lib/run-chart';
import type { Automation, RunSummary } from '../../../lib/automations/api';
import type { TaskManagerSchedule } from '../../../lib/task-manager-schedules/task-manager-scheduled';

const NOW = 1_800_000_000;

function run(over: Partial<RunSummary> = {}): RunSummary {
  return { run_id: 'r1', automation_id: 'a1', trigger: 'schedule', status: 'succeeded', started_at: NOW - 100, ended_at: NOW - 40, ...over } as RunSummary;
}

function auto(id: string, name: string, over: Partial<Automation> = {}): Automation {
  return { automation_id: id, name, enabled: true, next_fire_at: null, project_id: null, target: { kind: 'recipe' }, last_run: null, ...over } as Automation;
}

function item(n: number, over: Partial<TaskManagerSchedule> = {}): TaskManagerSchedule {
  return { list: '12', item: n, title: `task ${n}`, fireAt: NOW + n * 60, paused: false, state: 'pending', sessionKey: null, project: 'carnivore', ...over };
}

describe('resultOf', () => {
  test('a succeeded run is ok, a failed run is error, anything else that ended is skipped', () => {
    expect(resultOf('succeeded')).toBe('ok');
    expect(resultOf('failed')).toBe('error');
    expect(resultOf('cancelled')).toBe('skipped');
  });
});

describe('what ran it', () => {
  test('the trigger in friendly words', () => {
    expect(byWords(run()).key).toBe('opscenter.chart.by.schedule');
    expect(byWords(run({ trigger: 'catch_up' })).key).toBe('opscenter.chart.by.catch_up');
    expect(byWords(run({ trigger: 'retry' })).key).toBe('opscenter.chart.by.retry');
  });

  test('run now names who pressed it from the run notes: you, an agent by its session name, or an unnamed agent', () => {
    expect(byWords(run({ trigger: 'run_now', notes: { by: { kind: 'app' } } })).key).toBe('opscenter.chart.by.run_now_owner');
    expect(byWords(run({ trigger: 'run_now', notes: { by: { kind: 'app', name: 'sam' } } }))).toEqual({ key: 'opscenter.chart.by.run_now_named', params: { name: 'sam' } });
    expect(byWords(run({ trigger: 'run_now', notes: { by: { kind: 'mcp', tmux: 'carnivore_x', name: 'fix login' } } }))).toEqual({ key: 'opscenter.chart.by.run_now_named', params: { name: 'fix login' } });
    expect(byWords(run({ trigger: 'run_now', notes: { by: { kind: 'mcp' } } })).key).toBe('opscenter.chart.by.run_now_agent');
    expect(byWords(run({ trigger: 'run_now', notes: null })).key).toBe('opscenter.chart.by.run_now');
  });
});

describe('the area', () => {
  test('the target session, else the project, else the machine', () => {
    expect(automationArea(auto('a', 'x', { target: { kind: 'session_message', session_name: 'fix login' }, project_id: 3 }), { 3: 'carnivore' })).toBe('fix login');
    expect(automationArea(auto('a', 'x', { project_id: 3 }), { 3: 'carnivore' })).toBe('carnivore');
    expect(automationArea(auto('a', 'x', { target: { kind: 'command', project_id: 3 } }), { 3: 'carnivore' })).toBe('carnivore');
    expect(automationArea(auto('a', 'x'), {})).toBeNull();
  });
});

describe('scheduledChart', () => {
  const automations = [
    auto('a1', 'nightly', { last_run: run({ trigger: 'run_now', notes: { by: { kind: 'app' } } }), next_fire_at: NOW + 600 }),
    auto('a2', 'busy', { last_run: run({ status: 'running', started_at: NOW - 30, ended_at: null }) }),
    auto('a3', 'never run', { next_fire_at: NOW + 60 }),
    auto('a4', 'off and never run', { enabled: false, next_fire_at: NOW + 5 }),
    auto('a5', 'older', { last_run: run({ status: 'failed', ended_at: NOW - 900, started_at: NOW - 905 }) }),
  ];
  const input = { automations, projects: {}, huddle: [item(2), item(1), item(3, { paused: true, fireAt: NOW + 10 })] };

  test('global rows: one per automation that ran or is due, the running one first, then newest, then soonest due', () => {
    const rows = scheduledChart(input, NOW * 1000, 'global');
    expect(rows.map((r) => [r.name, r.mark, r.runSeconds, r.agoSeconds, r.nextSeconds])).toEqual([
      ['busy', 'running', 30, null, null],
      ['nightly', 'ok', 60, 40, 600],
      ['older', 'error', 5, 900, null],
      ['never run', 'none', null, null, 60],
    ]);
    expect(rows.every((r) => r.scope === 'global')).toBe(true);
    expect(rows[1]!.by?.key).toBe('opscenter.chart.by.run_now_owner');
    expect(rows[3]!.by).toBeNull();
  });

  test('sessions rows: the huddle items, soonest first, a paused repeat last with no next run', () => {
    const rows = scheduledChart(input, NOW * 1000, 'sessions');
    expect(rows.map((r) => [r.name, r.nextSeconds, r.paused, r.area])).toEqual([
      ['task 1', 60, false, 'carnivore'], ['task 2', 120, false, 'carnivore'], ['task 3', null, true, 'carnivore'],
    ]);
    expect(rows.every((r) => r.scope === 'sessions' && r.by?.key === 'opscenter.chart.by.schedule')).toBe(true);
  });

  test('both shows the global rows then the sessions rows', () => {
    const rows = scheduledChart(input, NOW * 1000, 'both');
    expect(rows.map((r) => r.scope)).toEqual(['global', 'global', 'global', 'global', 'sessions', 'sessions', 'sessions']);
  });

  test('a huddle item on the shared list is marked shared', () => {
    expect(scheduledChart({ automations: [], projects: {}, huddle: [item(1, { list: 'all', project: null })] }, NOW * 1000, 'sessions')[0]!.shared).toBe(true);
  });
});

describe('the columns', () => {
  test('narrow keeps the run time and drops the area first, then what ran it; wide shows all six', () => {
    expect(columnsFor(SCHEDULED_COLUMNS, 400, false).map((c) => c.key)).toEqual(['name', 'by', 'runTime', 'ago', 'next']);
    expect(columnsFor(SCHEDULED_COLUMNS, 300, false).map((c) => c.key)).toEqual(['name', 'runTime', 'ago', 'next']);
    expect(columnsFor(SCHEDULED_COLUMNS, 600, false).find((c) => c.key === 'next')?.minCh).toBe(10);
    expect(columnsFor(SCHEDULED_COLUMNS, 600, false).map((c) => c.key)).toEqual(['name', 'by', 'area', 'runTime', 'ago', 'next']);
  });

  test('a weekly or monthly next run fits its column: it reads in days, never ellipsized', () => {
    const minCh = columnsFor(SCHEDULED_COLUMNS, 600, false).find((c) => c.key === 'next')?.minCh ?? 0;
    for (const days of [1, 7, 31, 99]) expect(minCh).toBeGreaterThanOrEqual(nextWords(days * 86_400 + 3_599).length);
    expect(nextWords(7 * 86_400)).toBe('in 7d 00h');
    const [row] = scheduledChart({ automations: [auto('w', 'weekly', { last_run: run({}), next_fire_at: NOW + 7 * 86_400 })], projects: {}, huddle: [] }, NOW * 1000, 'global');
    expect(nextWords(row!.nextSeconds)).toBe('in 7d 00h');
  });
});
