import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';

export type SshState = 'not_set_up' | 'off' | 'host_key_not_confirmed' | 'did_not_answer' | 'taking_work' | 'not_a_job_target' | 'host_disabled' | 'host_key_changed';

export interface SshCan {
  os?: string | null;
  os_version?: string | null;
  arch?: string | null;
  cores?: number | null;
  mem_gb?: number | null;
  gpus?: { vendor?: string | null; model?: string | null; vram_gb?: number | null }[];
  tools?: Record<string, boolean>;
  labels?: string[];
}

export interface SshTarget {
  host_key: string;
  label: string;
  state: SshState;
  reason: string | null;
  takes_work: boolean;
  pinned: boolean;
  fingerprint: string | null;
  can: SshCan | null;
  pressure: { pegged?: boolean; why?: string | null } | null;
  age_s: number | null;
  last_ok_age_s: number | null;
  last_error: string | null;
  live_jobs: number;
}

export interface HostKeyShown {
  fingerprints: { sha256: string; type: string }[];
  known: 'new' | 'same' | 'changed';
  pinned: string | null;
  changed_since_shown: boolean;
}

export interface SshForgetResult {
  forgotten: string[];
  kept: { project: string; slot: string }[];
  refused: { project: string; code: string }[];
}

export interface SshTargetsApi {
  list(): Promise<SshTarget[]>;
  set(hostKey: string, body: { takes_work: boolean; host_key_sha256?: string; labels?: string[] }): Promise<SshTarget>;
  check(hostKey: string): Promise<{ fresh: boolean; target: SshTarget }>;
  forget(hostKey: string): Promise<SshForgetResult>;
}

const path = (key: string): string => `/pack/ssh-targets/${encodeURIComponent(key)}`;

export const sshTargetsApi: SshTargetsApi = {
  list: async () => (await authFetch<{ targets?: SshTarget[] }>('/pack/ssh-targets', { method: 'GET' })).targets ?? [],
  set: async (key, body) => (await authFetch<{ target: SshTarget }>(path(key), { method: 'PUT', body: JSON.stringify(body) })).target,
  check: async (key) => authFetch<{ fresh: boolean; target: SshTarget }>(`${path(key)}/probe`, { method: 'POST' }),
  forget: async (key) => authFetch<SshForgetResult>(`${path(key)}/folders`, { method: 'DELETE' }),
};

export function hostKeyShown(failure: unknown): HostKeyShown | null {
  if (!(failure instanceof ApiError) || failure.status !== 409 || failure.code !== 'confirm_host_key') return null;
  const detail = (failure.payload as { detail?: Partial<HostKeyShown> } | null)?.detail;
  if (!detail || !Array.isArray(detail.fingerprints) || detail.fingerprints.length === 0) return null;
  return { fingerprints: detail.fingerprints, known: detail.known ?? 'new', pinned: detail.pinned ?? null, changed_since_shown: detail.changed_since_shown === true };
}
