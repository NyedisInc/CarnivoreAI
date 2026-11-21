import { nonEmptyErrorMessageOr } from '../errors/failure-reason';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import { sshTargetsApi, type SshTarget, type SshTargetsApi } from './ssh-targets-api';

export const sshTargets = $state<{ list: SshTarget[]; loaded: boolean; error: string | null; changed: Record<string, boolean> }>({ list: [], loaded: false, error: null, changed: {} });

export async function loadSshTargets(api: SshTargetsApi = sshTargetsApi): Promise<void> {
  try {
    sshTargets.list = await api.list();
    sshTargets.error = null;
  } catch (failure) {
    sshTargets.error = nonEmptyErrorMessageOr(failure, t('pack.ssh.error.failed'));
  }
  sshTargets.loaded = true;
}

export function targetOf(hostKey: string): SshTarget | null {
  return sshTargets.list.find((x) => x.host_key === hostKey) ?? null;
}

export function takeTarget(target: SshTarget): void {
  const i = sshTargets.list.findIndex((x) => x.host_key === target.host_key);
  sshTargets.list = i < 0 ? [...sshTargets.list, target] : sshTargets.list.map((x, n) => (n === i ? target : x));
  if (target.state === 'taking_work') delete sshTargets.changed[target.host_key];
}

export function markChanged(hostKey: string): void {
  sshTargets.changed[hostKey] = true;
}

export const isKeyChanged = (failure: unknown): boolean => failure instanceof ApiError && failure.status === 409 && failure.code === 'host_key_changed';
