
import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import { errorMessageOr } from '../errors/failure-reason';

export interface ReserveLevel {
  cpu_pct: number;
  mem_pct: number;
}

export interface ReserveConfig {
  in_use: ReserveLevel;
  away: ReserveLevel;
  schedule: { in_use_from: string; in_use_to: string; days: number[] };
  keyboard_rule: { enabled: boolean; idle_minutes: number };
}

export interface Restrictions {
  may_install_tools: boolean;
  may_receive_credentials: boolean;
  may_update_carnivore: boolean;
  may_host_agents: boolean;
  may_receive_projects: boolean;
  max_agents: number | null;
  allowed_projects: string[];
  allowed_companies: string[];
}

export interface ActiveReserve {
  level: 'in_use' | 'away';
  cpu_pct: number;
  mem_pct: number;
  source: string;
  config?: ReserveConfig;
}

export interface AgentLoad {
  session_id: number;
  session_uuid: string;
  agent_id: number | null;
  name: string;
  cpu_pct: number;
  rss_mb: number;
}

export interface AgentsSection {
  rows: AgentLoad[];
  truncated: number;
  count: number;
  carnivore: { cpu_pct: number; rss_mb: number; agents: number };
  machine: { cpu_pct: number; rss_mb: number };
}

export interface MachineSnapshot {
  load: {
    cores: number | null;
    load_1: number | null;
    memory_percent: number | null;
    mem_total_gb?: number | null;
    disk_percent: number | null;
    disk_free_gb?: number | null;
  };
  battery: { present?: boolean; on_battery?: boolean | null; percent?: number | null; charging?: boolean | null } | null;
  reserve: ActiveReserve;
  restrictions: Restrictions;
  toolchain?: Record<string, boolean> | null;
  app_version?: string;
  agents?: AgentsSection | null;
  throttled?: number;
}

export interface PackMachine {
  install_id: string;
  host_key?: string | null;
  label: string;
  is_self: boolean;
  is_master: boolean;
  paired: boolean;
  state: string;
  capabilities: string[];
  specs: { model?: string | null; cores?: number | null; mem_total_gb?: number | null } | null;
  snapshot: MachineSnapshot | null;
  age_seconds: number | null;
}

export interface PackMachinesView {
  master_install_id: string | null;
  self_install_id: string;
  settings: {
    master_install_id?: string | null;
    placement_mode: string;
    auto_distribute: boolean;
    placement_model?: { connection: string; model: string } | null;
  };
  disagreement: string[] | null;
  machines: PackMachine[];
}

/* the push topic */
export const PACK_MACHINES_POLL_MS = 15000;

export const packMachines: Resource<PackMachinesView> = resource<PackMachinesView>(
  () => authFetch<PackMachinesView>('/pack/machines'),
  {
    intervalMs: PACK_MACHINES_POLL_MS,
    name: 'pack-machines',
    topics: ['pack_machines'],
    body: { key: 'pack_machines', renewMs: 30000, read: (body) => (body as PackMachinesView | null) ?? null },
  },
);

export const tracksMaster: Resource<{ tracks_master: boolean }> = resource<{ tracks_master: boolean }>(
  () => authFetch<{ tracks_master: boolean }>('/pack/tracks-master'),
  { intervalMs: 30000, name: 'pack-tracks-master' },
);

export const packActivity = $state<{ busy: string | null; error: string | null }>({ busy: null, error: null });

async function write(key: string, send: () => Promise<unknown>): Promise<void> {
  if (packActivity.busy) return;
  packActivity.busy = key;
  packActivity.error = null;
  try {
    await send();
  } catch (error) {
    packActivity.error = errorMessageOr(error, t('pack.machines.error.failed'));
  } finally {
    packActivity.busy = null;
    await packMachines.refresh(true);
  }
}

export function makeMaster(machine: string): Promise<void> {
  return write(`master:${machine}`, () =>
    authFetch('/pack/master', { method: 'PUT', body: JSON.stringify({ machine }) }));
}

export function updateSettings(patch: {
  placement_mode?: string;
  auto_distribute?: boolean;
  placement_model?: { connection: string; model: string } | null;
}): Promise<void> {
  return write('settings', () => authFetch('/pack/settings', { method: 'PUT', body: JSON.stringify(patch) }));
}

export function saveReserve(machine: string, patch: Partial<ReserveConfig>): Promise<void> {
  return write(`reserve:${machine}`, () =>
    authFetch(`/pack/machines/${encodeURIComponent(machine)}/reserve`, { method: 'PUT', body: JSON.stringify(patch) }));
}

export function saveRestrictions(machine: string, patch: Partial<Restrictions>): Promise<void> {
  return write(`restrictions:${machine}`, () =>
    authFetch(`/pack/machines/${encodeURIComponent(machine)}/restrictions`, { method: 'PUT', body: JSON.stringify(patch) }));
}

export async function setTracksMaster(value: boolean): Promise<void> {
  await write('tracks_master', () => authFetch('/pack/tracks-master', { method: 'PUT', body: JSON.stringify({ tracks_master: value }) }));
  await tracksMaster.refresh(true);
}
