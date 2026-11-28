import { authFetch } from '../../opscenter/api/auth.svelte';

export interface PackComputer {
  install_id: string;
  label: string;
  is_self: boolean;
  state: string;
  online: boolean;
  cores: number | null;
  cpu_pct: number | null;
  cpu_headroom_cores: number | null;
  mem_total_gb: number | null;
  mem_available_gb: number | null;
  ram_pct: number | null;
  mem_headroom_gb: number | null;
  pegged: boolean;
  live_agents: number;
  live_commands: number;
  live_delegated_agents: number;
  live_total: number;
  history_agents: number;
  history_commands: number;
  history_delegated_agents: number;
  history_total: number;
}

export interface StartedBy {
  label: string;
  session_uuid: string | null;
  kind: 'session' | 'owner' | 'external' | string;
}

export interface PackActivityItem {
  id: string;
  item_type: 'agent' | 'delegated_agent' | 'command' | string;
  live: boolean;
  status: string;
  tone: 'ok' | 'danger' | 'warn' | 'info' | 'neutral';
  title: string;
  project: string;
  computer_id: string;
  computer_label: string;
  source_computer_label: string | null;
  started_by: StartedBy;
  started_at: number;
  ended_at: number | null;
  duration_s: number;
  agent_type: string;
  reason: string | null;
  session_uuid: string | null;
  job_id: string | null;
  can_stop: boolean;
  origin_scope: 'local' | 'hosted' | 'peer_session' | 'peer_to_peer' | string;
  exit_code?: number | null;
}

export interface PackActivityAggregate {
  online_machines?: number;
  total_machines?: number;
  total_cores?: number;
  busy_cores?: number;
  fleet_cpu_pct?: number | null;
  usable_free_cores?: number;
  total_ram_gb?: number;
  used_ram_gb?: number;
  fleet_ram_pct?: number | null;
  usable_free_ram_gb?: number;
  live_agents_total: number;
  live_jobs_total: number;
  history_total: number;
  peer_fanout: { queried: number; ok: number; skipped: number };
}

export interface PackActivityResponse {
  days: number;
  generated_at: number;
  computers: PackComputer[];
  fleet_aggregate: PackActivityAggregate;
  items: PackActivityItem[];
  total_items: number;
  efficiency: {
    p50_overhead_s?: number | null;
    p50_run_s?: number | null;
    overhead_ratio?: number | null;
  };
  guard_health: {
    funnel?: Record<string, number>;
  };
  utilization_history: {
    pegged_minutes_total: number;
    idle_while_peer_pegged_minutes: number;
  };
  summary: {
    r3_remote_share?: number | null;
    p3_miss_share?: number | null;
    guard_giveways?: number;
  };
}

export interface PackActivityQuery {
  days?: number;
  limit?: number;
  includePeers?: boolean;
}

export interface PackActivityApi {
  read(query?: PackActivityQuery): Promise<PackActivityResponse>;
}

export const activityApi: PackActivityApi = {
  read: (query = {}) => {
    const params = new URLSearchParams();
    if (query.days) params.set('days', String(query.days));
    if (query.limit) params.set('limit', String(query.limit));
    if (query.includePeers !== undefined) params.set('include_peers', String(query.includePeers));
    const qs = params.toString();
    return authFetch<PackActivityResponse>(`/pack/activity${qs ? `?${qs}` : ''}`, { method: 'GET' });
  },
};
