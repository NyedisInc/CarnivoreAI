import type { WidgetFixtures } from './types';

export const machineStatsFixtures: WidgetFixtures = {
  data: {
    'GET /machine-stats': {
      cpu_percent: 23.4, cpu_count: 10, memory_percent: 62.0, memory_used_bytes: 21_400_000_000,
      memory_total_bytes: 34_400_000_000, disk_percent: 71.5, disk_free_bytes: 142_000_000_000,
      disk_total_bytes: 500_000_000_000, load_1: 2.41, load_5: 1.87, load_15: 1.52, uptime_seconds: 273600,
    },
  },
  empty: {
    'GET /machine-stats': {
      cpu_percent: null, cpu_count: null, memory_percent: null, memory_used_bytes: null, memory_total_bytes: null,
      disk_percent: null, disk_free_bytes: null, disk_total_bytes: null, load_1: null, load_5: null, load_15: null,
      uptime_seconds: null,
    },
  },
};
