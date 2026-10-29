import { authFetch } from '../../../opscenter/api/auth.svelte';

export interface PeerStatus {
  label: string;
  state: string;
  applied_gen: number | null;
  off_count: number | null;
  conflicts: [string, string, string][];
}

export interface PackRow {
  family: 'claude' | 'codex';
  name: string;
  synced: boolean;
  state: string;
  reason?: string;
  digest?: string;
  placed_by?: { id: string; label: string };
  warez?: { item: string; version: string };
  cells?: Record<string, string>;
}

export interface TakePreview {
  family: string;
  name: string;
  digest: string;
  files: number;
  bytes: number;
  scripts: string[];
  here: 'absent' | 'same' | 'differs';
  from: string;
  plan_token: string;
}

/* could not be written */
export interface TakeResult {
  ok: boolean;
  placed: number;
  conflicts: string[];
}

export interface Choices {
  mode: 'off' | 'some' | 'all';
  include: string[][];
  exclude: string[][];
}

export interface PackSkills {
  role: 'alpha' | 'receiver';
  read_only?: boolean;
  alpha: { id: string; label: string };
  gen?: number;
  applied_gen?: number;
  problem?: string | null;
  hold?: Record<string, unknown> | null;
  choices?: Choices;
  peers?: Record<string, PeerStatus>;
  rows: PackRow[];
}

export interface PreviewComputer {
  id: string;
  label: string;
  state: string;
  add: number;
  replace: number;
  same: number;
  conflict: number;
  skills: Record<string, string>;
}

export interface Preview {
  skills: { family: string; name: string; size: number; files: number; scripts: string[]; problem: string | null }[];
  computers: PreviewComputer[];
  total_bytes: number;
  total_files: number;
  others?: number;
  choices: Choices;
  plan_token: string;
}

export type PlanCall =
  | { kind: 'mode'; mode: 'all' | 'off' }
  | { kind: 'skill'; family: string; families?: string[]; name: string; synced: boolean; removeElsewhere: boolean };

export function getPackSkills(inventory = false): Promise<PackSkills> {
  return authFetch(`/pack/skills${inventory ? '?inventory=true' : ''}`);
}

export interface SkillDetail {
  family: string;
  name: string;
  machine_local: string[];
  here: { digest: string; problem: string | null; scripts: string[]; files: { path: string; size: number; sha256: string }[] } | null;
  computers?: { id: string; label: string; state: string; digests: string[]; from_warez: boolean }[];
}

export function getDetail(family: string, name: string): Promise<SkillDetail> {
  return authFetch(`/pack/skills/${family}/${encodeURIComponent(name)}`);
}

export function runPlan(call: PlanCall, dryRun: boolean, token?: string): Promise<Preview & { ok?: boolean }> {
  const common = { dry_run: dryRun, ...(token ? { plan_token: token } : {}) };
  if (call.kind === 'mode') {
    return authFetch('/pack/skills/choices', { method: 'PUT', body: JSON.stringify({ mode: call.mode, include: [], exclude: [], ...common }) });
  }
  return authFetch(`/pack/skills/${call.family}/${encodeURIComponent(call.name)}`, {
    method: 'PUT',
    body: JSON.stringify({ synced: call.synced, ...(call.families ? { families: call.families } : {}), remove_elsewhere: call.removeElsewhere, ...common }),
  });
}

export function takeCopy(from: string, family: string, name: string, dryRun: boolean, token?: string): Promise<TakePreview & TakeResult> {
  return authFetch('/pack/skills/take', {
    method: 'POST',
    body: JSON.stringify({ from_install_id: from, family, name, dry_run: dryRun, ...(token ? { plan_token: token } : {}) }),
  });
}

export function postHeld(family: string, name: string, action: 'stop_syncing' | 'remove_everywhere' | 'publish_mine'): Promise<{ ok: boolean }> {
  return authFetch(`/pack/skills/${family}/${encodeURIComponent(name)}/held`, { method: 'POST', body: JSON.stringify({ action }) });
}

export function syncNow(): Promise<{ ok: boolean }> {
  return authFetch('/pack/skills/sync-now', { method: 'POST', body: '{}' });
}

export function refusalCode(error: unknown): string | null {
  const code = (error as { payload?: { detail?: { code?: unknown } } } | null)?.payload?.detail?.code;
  return typeof code === 'string' ? code : null;
}
