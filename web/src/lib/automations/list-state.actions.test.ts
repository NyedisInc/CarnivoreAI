import { beforeEach, expect, test, vi } from 'vitest';

const stub = vi.hoisted(() => ({
  listAutomations: vi.fn(), listTargets: vi.fn(), getRunCounts: vi.fn(), listRuns: vi.fn(), listProjectChoices: vi.fn(),
  listSessionRecords: vi.fn(), createAutomation: vi.fn(), getRun: vi.fn(), listFeed: vi.fn(),
}));
vi.mock('./api', () => stub);
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {}, onChange: () => () => {} }) }));

import { compareWithPrevious, duplicate } from './list-state.svelte';
import { data } from './page-store.svelte';

const base = {
  automation_id: 'aut_1', name: 'nightly', enabled: true, revision: 1, trigger: { cron: '0 3 * * *', timezone: 'UTC' },
  delivery: { notify: true, notify_on: null }, description: '', project_id: null, misfire: 'run_once', retry_max: 0,
  retry_backoff_s: 300, max_runtime_s: null,
};

beforeEach(() => {
  Object.values(stub).forEach((fn) => fn.mockReset());
  stub.listAutomations.mockResolvedValue({ automations: [] });
  stub.listTargets.mockResolvedValue({ kinds: [], commands: [], recipes: [] });
  stub.getRunCounts.mockResolvedValue({});
  stub.listProjectChoices.mockResolvedValue([]);
  stub.createAutomation.mockImplementation(async (d: { name: string }) => ({ ...base, ...d, automation_id: 'aut_2' }));
  data.paneMode = null;
  data.seed = null;
});

test('a duplicate is created switched off', async () => {
  await duplicate({ ...base, target: { kind: 'command', command: '/usr/bin/git pull', project_id: null } } as never);
  expect(stub.createAutomation).toHaveBeenCalledTimes(1);
  expect(stub.createAutomation.mock.calls[0]![0].enabled).toBe(false);
});

test('a copy of an unattended agent opens the new editor instead of a create the server would refuse', async () => {
  const target = { kind: 'agent', prompt: 'go', permission: 'unattended', acknowledge_unattended: 'I accept' };
  await duplicate({ ...base, target } as never);
  expect(stub.createAutomation).not.toHaveBeenCalled();
  expect(data.paneMode).toBe('new');
  expect(data.seed?.target).toMatchObject({ kind: 'agent', permission: 'unattended' });
  expect(data.seed?.target).not.toHaveProperty('acknowledge_unattended');
});

const run = (id: string, status: string, extra: Record<string, unknown> = {}) => ({
  run_id: id, number: 1, status, reason: null, trigger: 'schedule', slot_at: 1, started_at: 1, ended_at: 2, has_report: true,
  report: { summary: 'x' }, ...extra,
});

test('the comparison of a run still live is not cached', async () => {
  stub.listRuns.mockResolvedValue({ runs: [run('live', 'running')] });
  await compareWithPrevious('aut_1', { run_id: 'live' });
  await compareWithPrevious('aut_1', { run_id: 'live' });
  expect(stub.listRuns).toHaveBeenCalledTimes(2);
});

test('a finished run is read once', async () => {
  stub.listRuns.mockResolvedValue({ runs: [run('done', 'succeeded')] });
  await compareWithPrevious('aut_1', { run_id: 'done' });
  await compareWithPrevious('aut_1', { run_id: 'done' });
  expect(stub.listRuns).toHaveBeenCalledTimes(1);
});

test('a run whose report was left out of the budget is fetched, not read as having no report', async () => {
  stub.listRuns.mockResolvedValue({ runs: [run('b', 'succeeded', { has_report: true, report_omitted: true, report: undefined }), run('c', 'succeeded', { report_omitted: true, report: undefined })] });
  stub.getRun.mockResolvedValue(run('b', 'succeeded'));
  await compareWithPrevious('aut_1', { run_id: 'c' });
  expect(stub.getRun).toHaveBeenCalled();
});
