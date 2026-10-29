import { afterEach, describe, expect, test, vi } from 'vitest';

vi.mock('./api', () => ({ getRun: vi.fn(async () => ({ run_id: 'r9', status: 'succeeded', report: { x: 1 } })) }));
import { keepReport, reports } from './feed-store.svelte';

afterEach(() => { for (const k of Object.keys(reports)) delete reports[k]; });

const run = (over: Record<string, unknown>) => ({ run_id: 'r1', status: 'succeeded', has_report: true, report: { a: 1 }, ...over });

describe('keepReport', () => {
  test('stores the inlined report of a terminal run', () => {
    keepReport(run({}));
    expect(reports.r1).toEqual({ state: 'ready', report: { a: 1 } });
  });
  test('ignores a live run, a run with no report and an already cached run', () => {
    keepReport(run({ status: 'running' }));
    keepReport(run({ run_id: 'r2', has_report: false }));
    reports.r3 = { state: 'ready', report: 'kept' };
    keepReport(run({ run_id: 'r3' }));
    expect(Object.keys(reports).sort()).toEqual(['r3']);
    expect(reports.r3).toEqual({ state: 'ready', report: 'kept' });
  });
  test('an omitted report is never stored as empty; it is queued only when asked', async () => {
    keepReport(run({ run_id: 'r4', report_omitted: true, report: undefined }));
    expect(reports.r4).toBeUndefined();
    keepReport(run({ run_id: 'r9', report_omitted: true }), true);
    await vi.waitFor(() => expect(reports.r9).toEqual({ state: 'ready', report: { x: 1 } }));
  });
});
