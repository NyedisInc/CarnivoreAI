/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ fitTableState: vi.fn(), startMatrix: vi.fn() }));
vi.mock('./lab-api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./lab-api')>()), ...api }));

import { MATRIX_POLL_MS, MatrixRunner } from './matrix-runner.svelte';

const RUNNING = { available: true, reason: '', running: true, started: null, exit: null, table: null };
const DONE = { ...RUNNING, running: false };

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(console, 'warn').mockImplementation(() => undefined);
  api.fitTableState.mockReset();
});
afterEach(() => vi.useRealTimers());

it('asks again after a failed read while the last known state was running, and stops once the run is done', async () => {
  const runner = new MatrixRunner(() => undefined);
  api.fitTableState.mockResolvedValueOnce(RUNNING).mockRejectedValueOnce(new Error('restarting')).mockResolvedValueOnce(DONE);
  await runner.refresh();
  await vi.advanceTimersByTimeAsync(MATRIX_POLL_MS);
  expect(api.fitTableState).toHaveBeenCalledTimes(2);
  expect(runner.refusal).not.toBe('');
  await vi.advanceTimersByTimeAsync(MATRIX_POLL_MS * 2);
  expect(api.fitTableState).toHaveBeenCalledTimes(3);
  expect(runner.state?.running).toBe(false);
  await vi.advanceTimersByTimeAsync(MATRIX_POLL_MS * 10);
  expect(api.fitTableState).toHaveBeenCalledTimes(3);
  runner.destroy();
});

it('does not poll after a failed first read (nothing was running)', async () => {
  const runner = new MatrixRunner(() => undefined);
  api.fitTableState.mockRejectedValue(new Error('down'));
  await runner.refresh();
  await vi.advanceTimersByTimeAsync(MATRIX_POLL_MS * 10);
  expect(api.fitTableState).toHaveBeenCalledTimes(1);
  runner.destroy();
});
