
export interface PerfServerSample {
  type: 'perf.sample';
  window_s: number;
  loop_lag_ms: { p50: number | null; p99: number | null; max: number | null; minute_max: number | null; stalls_per_min: number };
  requests_per_min: number;
  routes: { method: string; route: string; per_min: number; avg_ms: number; busy_pct: number }[];
  ws: { channel: string; topic: string; per_min: number; bytes_per_s: number }[];
  ws_clients: { channel: string; client: string; per_min: number; bytes_per_s: number }[];
  watcher_ms: Record<string, { passes_per_min: number; p50: number | null; max: number }>;
  processes: {
    server: { pid: number; cpu_pct: number | null; rss_mb: number } | null;
    tmux: Record<string, { pid: number; cpu_pct: number | null; rss_mb: number }>;
  } | null;
}

export interface PerfClientSnapshot {
  echo: { net_ms: number | null; painted_ms: number | null; worst_ms: number | null; samples: number };
  rx: { path: string; msgs_per_s: number; bytes_per_s: number }[];
  frames_per_s: number;
  pollers: { kind: 'interval' | 'resource'; name: string; ms: number; where: string }[];
  server: PerfServerSample | null;
}

export interface PerfProbeApi {
  install(): void;
  uninstall(): void;
  isInstalled(): boolean;
  snapshot(): PerfClientSnapshot | null;
  remember(on: boolean): void;
  registerPollerSource(fn: () => { name: string; intervalMs: number }[]): void;
  acceptServerSample(frame: unknown): void;
  onServerSample(fn: (frame: unknown) => void): () => void;
}
