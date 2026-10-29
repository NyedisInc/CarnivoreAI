import { describe, expect, test } from 'vitest';
import { failedAutomationRows } from './rows';
import type { RunRow } from '../../opscenter/cells/developer/model';

const run = (id: string, auto: string, status: string, ended: number | null, extra: Partial<RunRow> = {}): RunRow =>
  ({ run_id: id, automation_id: auto, automation_name: `name ${auto}`, status, ended_at: ended, started_at: ended, slot_at: ended, ...extra }) as RunRow;

describe('failedAutomationRows', () => {
  test('an automation whose latest result failed is one row, keyed and targeted by the automation', () => {
    const rows = failedAutomationRows([run('r2', 'a', 'failed', 200), run('r1', 'a', 'succeeded', 100)]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ key: 'automation:a', kindId: 'automations', source: 'automation', severity: 'error', what: 'name a', atMs: 200_000, target: { source: 'automation', automationId: 'a' } });
  });

  test('a later success clears an earlier failure', () => {
    expect(failedAutomationRows([run('r2', 'a', 'succeeded', 200), run('r1', 'a', 'failed', 100)])).toEqual([]);
  });

  test('a live, skipped or cancelled run neither raises nor clears a failure', () => {
    const rows = failedAutomationRows([run('r4', 'a', 'running', null), run('r3', 'a', 'skipped', 300), run('r2', 'a', 'cancelled', 250), run('r1', 'a', 'failed', 100)]);
    expect(rows.map((r) => r.key)).toEqual(['automation:a']);
    expect(failedAutomationRows([run('r2', 'b', 'skipped', 300), run('r1', 'b', 'succeeded', 100)])).toEqual([]);
  });

  test('each automation is judged on its own run, and the order the server sent does not matter', () => {
    const rows = failedAutomationRows([run('x1', 'a', 'failed', 100), run('y2', 'b', 'failed', 90), run('y1', 'b', 'succeeded', 10), run('x2', 'a', 'succeeded', 200)]);
    expect(rows.map((r) => r.key)).toEqual(['automation:b']);
  });

  test('no runs is no rows', () => {
    expect(failedAutomationRows([])).toEqual([]);
  });
});
