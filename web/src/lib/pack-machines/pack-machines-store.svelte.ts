
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
  may_receive_global_setup: boolean;
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

export interface CanGpu { vendor: string; model: string; vram_gb: number | null; discrete: boolean }

export interface CanBlock {
  v: number;
  rev: string;
  probed_at: number;
  os: string;
  os_version?: string | null;
  arch?: string | null;
  chip?: string | null;
  cores?: number | null;
  mem_gb?: number | null;
  gpus: CanGpu[];
  tools: Record<string, boolean>;
  xcode?: string | null;
  ios_sim: boolean;
  brew: boolean;
  labels: string[];
  installing?: string | null;
}

export interface PressureBlock {
  pegged: boolean;
  since: number | null;
  why?: string;
  busy_cores: number | null;
  line: number | null;
  cores: number | null;
  run_queue_per_core: number | null;
  mem: 'normal' | 'warn' | 'critical' | null;
  held?: { cpu: number; ram_gb: number; n: number };
  throttled?: number;
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
  can?: CanBlock | null;
  pressure?: PressureBlock | null;
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
  roster_v1?: boolean;
  eligible?: boolean;
  is_home?: boolean;
  rank?: number | null;
  can_claim?: boolean;
  link_path?: 'direct' | 'relay' | 'none' | null;
  relay_id_known?: boolean;
}

export type TakeoverReason = 'off' | 'no_eligible' | 'alpha_not_updated' | 'ok';

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
  generation?: number | null;
  roster_issued_at?: number | null;
  home_install_id?: string | null;
  interim?: boolean;
  takeover_available?: { ok: boolean; reason: TakeoverReason };
  reconnect?: { relay_on: boolean; takeover_on: boolean };
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
  { intervalMs: 30000, name: 'pack-tracks-master', topics: ['pack_tracks_master'] },
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
