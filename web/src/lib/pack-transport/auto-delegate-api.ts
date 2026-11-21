import { authFetch } from '../../opscenter/api/auth.svelte';

export interface AutoCopy {
  install_id: string;
  label: string;
  auto: boolean;
  root?: string;
}

export interface CopyRun {
  running: boolean;
  refused: Record<string, string>;
  error: string | null;
}

export interface RecentJob { id: string; kind: string | null; task_head: string | null; computer: string | null; created_at: number }

export interface AutoDelegateView {
  project_uid?: string;
  role: 'home' | 'copy' | 'moved';
  home_computer?: string;
  moved_to?: string;
  this_computer?: { install_id: string; label: string };
  is_repo?: boolean;
  live_jobs?: number;
  auto_delegate?: boolean;
  never_use?: string[];
  copies?: AutoCopy[];
  copy_run?: CopyRun;
  no_work?: string[];
  unregistered?: string[];
  failed?: { computer: string; code: string }[];
  handoff?: { machine: string; label: string } | null;
  deleted?: { label: string; root: string; code: string }[];
  ssh_forgotten?: { key: string; label: string; code: string }[];
  kept?: { label: string; code: string; root: string }[];
}

export interface AutoDelegateBody {
  on: boolean;
  never_use?: string[];
  wipe_others?: boolean;
  keep?: string;
  delete_copies?: boolean;
  delete_only?: string[];
}

export interface AutoDelegateApi {
  get(name: string): Promise<AutoDelegateView>;
  recentJobs(projectUid: string): Promise<RecentJob[]>;
  put(name: string, body: AutoDelegateBody): Promise<AutoDelegateView>;
}

const path = (name: string): string => `/projects/${encodeURIComponent(name)}/auto-delegate`;

export const autoDelegateApi: AutoDelegateApi = {
  get: (name) => authFetch<AutoDelegateView>(path(name), { method: 'GET' }),
  recentJobs: async (uid) => (await authFetch<{ jobs?: RecentJob[] }>(`/pack/jobs?project=${encodeURIComponent(uid)}&limit=3`, { method: 'GET' })).jobs ?? [],
  put: (name, body) => authFetch<AutoDelegateView>(path(name), { method: 'PUT', body: JSON.stringify(body) }),
};
