/* quotes the fingerprint */

import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';

export interface MigrateTarget {
  kind: 'project' | 'company' | 'back';
  name: string;
}

export interface PlanCheck {
  name: string;
  ok: boolean;
  detail: string;
  blocking: boolean;
  files?: string[];
  files_more?: number;
  files_unchecked?: number;
  files_check_failed?: boolean;
}

export interface PublishCard {
  name: string;
  owner: string | null;
  account: string | null;
  asks: string[];
  offered: boolean;
  reason: string | null;
}

export interface ProjectPlan {
  project: string;
  rung: 'git' | 'carried' | 'tar';
  rung_reason: string;
  one_way: boolean;
  target_root: string;
  checks: PlanCheck[];
  blocking: string[];
  summary: Record<string, number | null>;
  publish_card: PublishCard | null;
}

export interface PlanView {
  kind: string;
  name: string;
  machine: string;
  projects: ProjectPlan[];
  blocking: string[];
  can_apply: boolean;
  plan_fingerprint: string;
}

export interface BackView {
  name: string;
  machine: string;
}

export interface OpView {
  id: string;
  state: string;
  step: string | null;
  error_code: string | null;
  detail: Record<string, unknown>;
  steps: string[];
  children: { id: string; name: string | null; state: string; step: string | null; error_code: string | null; task_files_not_copied?: string[]; task_files_not_copied_more?: number }[];
}

export type Phase = 'pick' | 'plan' | 'running' | 'done' | 'failed';

export const migrate = $state<{
  target: MigrateTarget | null;
  phase: Phase;
  machine: string | null;
  plan: PlanView | null;
  back: BackView | null;
  opId: string | null;
  busy: boolean;
  error: string | null;
  confirmedOneWay: boolean;
  stopRunning: boolean;
}>({ target: null, phase: 'pick', machine: null, plan: null, back: null, opId: null, busy: false, error: null, confirmedOneWay: false, stopRunning: false });

/* the push topic */
export const PACK_OPS_POLL_MS = 3000;
let opResource = $state.raw<Resource<OpView> | null>(null);

export function followedOp(): Resource<OpView> | null {
  return opResource;
}

function base(target: MigrateTarget): string {
  return `${target.kind === 'company' ? '/companies' : '/projects'}/${encodeURIComponent(target.name)}`;
}

function words(error: unknown): string {
  return error instanceof Error && error.message ? error.message : t('pack.migrate.error.failed');
}

function stopOp(): void {
  opResource?.stop();
  opResource = null;
}

export function openMigrate(target: MigrateTarget): void {
  stopOp();
  Object.assign(migrate, { target, phase: 'pick', machine: null, plan: null, back: null, opId: null, busy: false, error: null, confirmedOneWay: false, stopRunning: false });
  if (target.kind === 'back') void planBack();
}

export function closeMigrate(): void {
  stopOp();
  migrate.target = null;
}

export async function planMove(machine: string): Promise<void> {
  const target = migrate.target;
  if (!target || migrate.busy) return;
  Object.assign(migrate, { busy: true, error: null, machine, plan: null, confirmedOneWay: false });
  try {
    const plan = await authFetch<PlanView>(`${base(target)}/migrate`, { method: 'POST', body: JSON.stringify(migrate.stopRunning ? { machine, stop_running: true } : { machine }) });
    migrate.plan = plan;
    migrate.phase = 'plan';
  } catch (error) {
    migrate.error = words(error);
  } finally {
    migrate.busy = false;
  }
}

async function planBack(): Promise<void> {
  const target = migrate.target;
  if (!target) return;
  migrate.busy = true;
  try {
    migrate.back = await authFetch<BackView>(`${base(target)}/migrate-back`, { method: 'POST', body: JSON.stringify({ apply: false }) });
    migrate.phase = 'plan';
  } catch (error) {
    migrate.error = words(error);
  } finally {
    migrate.busy = false;
  }
}

function follow(opId: string): void {
  stopOp();
  opResource = resource<OpView>(() => authFetch<OpView>(`/pack/ops/${encodeURIComponent(opId)}`), {
    intervalMs: PACK_OPS_POLL_MS,
    topics: [`pack_ops:${opId}`],
    name: `pack-ops:${opId}`,
  });
}

export function phaseOf(state: string): Phase {
  return state === 'flipped' || state === 'moved_back' ? 'done' : state === 'failed' ? 'failed' : 'running';
}

export async function applyMove(): Promise<void> {
  const target = migrate.target;
  if (!target || migrate.busy) return;
  migrate.busy = true;
  migrate.error = null;
  try {
    if (target.kind === 'back') {
      migrate.phase = 'running';
      const done = await authFetch<{ op_id?: string }>(`${base(target)}/migrate-back`, { method: 'POST', body: JSON.stringify({ apply: true }) });
      migrate.opId = done.op_id ?? null;
      migrate.phase = 'done';
      return;
    }
    const plan = migrate.plan;
    if (!plan || !migrate.machine) return;
    const started = await authFetch<{ op_id: string }>(`${base(target)}/migrate`, {
      method: 'POST',
      body: JSON.stringify({ machine: migrate.machine, apply: true, plan_fingerprint: plan.plan_fingerprint, ...(migrate.stopRunning ? { stop_running: true } : {}) }),
    });
    migrate.opId = started.op_id;
    migrate.phase = 'running';
    follow(started.op_id);
  } catch (error) {
    migrate.error = words(error);
    if (migrate.phase === 'running') migrate.phase = 'plan';
  } finally {
    migrate.busy = false;
  }
}

export async function publishRepo(owner: string, account: string): Promise<void> {
  const target = migrate.target;
  const machine = migrate.machine;
  const name = migrate.plan?.projects.find((p) => p.publish_card?.offered)?.project;
  if (!target || !machine || !name || migrate.busy) return;
  migrate.busy = true;
  migrate.error = null;
  try {
    await authFetch(`/projects/${encodeURIComponent(name)}/publish-repo`, {
      method: 'POST',
      body: JSON.stringify({ ...(owner ? { owner } : {}), ...(account ? { account } : {}) }),
    });
  } catch (error) {
    migrate.error = words(error);
    migrate.busy = false;
    return;
  }
  migrate.busy = false;
  await planMove(machine);
}
