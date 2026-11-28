/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import JobsNumbers from './JobsNumbers.svelte';
import type { Metrics, MetricsApi } from './metrics-api';
import type { JobsDelta } from './jobs-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const metrics = (over: Partial<Metrics['r3']> = {}, p3: Partial<Metrics['p3']> = {}): Metrics => ({
  days: 7, load: { hours: [] },
  p3: { window_days: 7, misses: 0, delegate_calls: 0, share: null, threshold: 0.3, over: false, enough_data: false, ...p3 },
  r3: { window_days: 7, remote_minutes: 150, local_minutes: 30, share: 0.833, ...over },
});
let answer: Metrics = metrics();
const read = vi.fn(async () => answer);
const api: MetricsApi = { read };
let feed: ((f: JobsDelta) => void) | null = null;
const mounted: ReturnType<typeof mount>[] = [];
const text = (root: HTMLElement, sel: string): string => root.querySelector(sel)?.textContent?.trim() ?? '';
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(JobsNumbers, { target, props: { api, subscribe: (h: (f: JobsDelta) => void) => { feed = h; return () => { feed = null; }; } } }));
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  return target;
}
const job = (state: string) => ({ id: 'j', side: 'caller', state } as never);

beforeEach(() => { vi.useFakeTimers(); read.mockClear(); answer = metrics(); feed = null; });
afterEach(() => { mounted.splice(0).forEach((m) => void unmount(m)); document.body.replaceChildren(); vi.useRealTimers(); });

describe('the numbers block', () => {
  test('shows the share and the hours from the answer', async () => {
    const root = await render();
    expect(text(root, '[data-jobs="numbers-share"]')).toContain('83%');
    expect(text(root, '[data-jobs="numbers-hours"]')).toContain('2.5 hours ran elsewhere');
    expect(text(root, '[data-jobs="numbers-hours"]')).toContain('0.5 hours stayed here');
  });

  test('no data shows "no heavy work measured yet"', async () => {
    answer = metrics({ share: null, remote_minutes: 0, local_minutes: 0 });
    const root = await render();
    expect(text(root, '[data-jobs="numbers-empty"]')).toBe('no heavy work measured yet.');
    expect(root.querySelector('[data-jobs="numbers-share"]')).toBeNull();
  });

  test('renders Pack fleet utilization, overhead, and guard funnel when loadReport is provided', async () => {
    const loadReport = vi.fn(async () => ({
      days: 7,
      fleet_now: {
        machines: [],
        aggregate: {
          online_machines: 3, total_machines: 3, total_cores: 34, busy_cores: 11.2,
          fleet_cpu_pct: 33.0, usable_free_cores: 17.6, total_ram_gb: 96, used_ram_gb: 48,
          fleet_ram_pct: 50.0, usable_free_ram_gb: 31.4, active_jobs: 2,
        },
      },
      utilization_history: { window_days: 7, pegged_minutes_total: 4, idle_while_peer_pegged_minutes: 1.5, by_machine: [] },
      efficiency: { window_days: 7, state_counts: {}, p50_overhead_s: 12.4, p50_run_s: 48.0, overhead_ratio: 0.21 },
      guard_health: { window_days: 7, funnel: { blocked_offload: 14, local_only_path: 5, gave_way: 2 }, top_giveways: [] },
      summary: { r3_remote_share: 0.83, p3_miss_share: 0.1, guard_giveways: 2 },
    }));
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(JobsNumbers, {
      target,
      props: { api: { read, loadReport }, subscribe: (h: (f: JobsDelta) => void) => { feed = h; return () => { feed = null; }; } },
    }));
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(loadReport).toHaveBeenCalledTimes(1);
    expect(text(target, '[data-jobs="numbers-fleet"]')).toContain('33% cpu');
    expect(text(target, '[data-jobs="numbers-fleet"]')).toContain('50% ram');
    expect(text(target, '[data-jobs="numbers-overhead"]')).toContain('12.4s');
    expect(text(target, '[data-jobs="numbers-guard"]')).toContain('14 offloaded');
  });

  test('reads once at open, again 10 s after a terminal frame, and never on a timer', async () => {
    await render();
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(120000);
    expect(read).toHaveBeenCalledTimes(1);
    feed!({ type: 'pack_jobs.delta', seq: 1, job: job('running') });
    await vi.advanceTimersByTimeAsync(20000);
    expect(read).toHaveBeenCalledTimes(1);
    feed!({ type: 'pack_jobs.delta', seq: 2, job: job('done') });
    await vi.advanceTimersByTimeAsync(9000);
    expect(read).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1500);
    expect(read).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(120000);
    expect(read).toHaveBeenCalledTimes(2);
  });
});
