
import { authFetch } from '../../api/auth.svelte';
import { resource, type Resource } from '../../api/poll.svelte';

export interface MachineStats {
  cpu_percent: number | null;
  cpu_count: number | null;
  memory_percent: number | null;
  memory_used_bytes: number | null;
  memory_total_bytes: number | null;
  disk_percent: number | null;
  disk_free_bytes: number | null;
  disk_total_bytes: number | null;
  load_1: number | null;
  load_5: number | null;
  load_15: number | null;
  uptime_seconds: number | null;
}

export const MACHINE_STATS_FALLBACK_MS = 15000;

export const MACHINE_STATS_TOPIC = 'machine_stats';

function demoStats(): MachineStats {
  return {
    cpu_percent: 12, cpu_count: 8, memory_percent: 41, memory_used_bytes: 13_200_000_000,
    memory_total_bytes: 32_000_000_000, disk_percent: 58, disk_free_bytes: 210_000_000_000,
    disk_total_bytes: 500_000_000_000, load_1: 1.2, load_5: 1.0, load_15: 0.9, uptime_seconds: 172800,
  };
}

export const machineStats = $state<{ current: Resource<MachineStats> | null }>({ current: null });

let holders = 0;
let offVisible: (() => void) | null = null;

/*  hidden  */
function make(): Resource<MachineStats> {
  let made: Resource<MachineStats> | null = null;
  made = resource<MachineStats>(
    () => {
      if (typeof document !== 'undefined' && document.hidden && made?.data) return Promise.resolve(made.data);
      return authFetch<MachineStats>('/machine-stats');
    },
    { intervalMs: MACHINE_STATS_FALLBACK_MS, name: 'machine-stats', demo: demoStats, topics: [MACHINE_STATS_TOPIC] },
  );
  return made;
}

export function acquireMachineStats(): () => void {
  holders += 1;
  if (holders === 1) {
    machineStats.current = make();
    const onVisible = (): void => {
      if (!document.hidden) void machineStats.current?.refresh(true);
    };
    document.addEventListener('visibilitychange', onVisible);
    offVisible = () => document.removeEventListener('visibilitychange', onVisible);
  }
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holders -= 1;
    if (holders === 0) {
      offVisible?.();
      offVisible = null;
      machineStats.current?.stop();
      machineStats.current = null;
    }
  };
}
