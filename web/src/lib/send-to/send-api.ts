import { authFetch } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';

export type SendMode = 'move' | 'copy' | 'fresh';

export interface Verdict {
  ok: boolean;
  reason?: string;
  detail?: string;
}

export interface SendCarry {
  units?: { kind: string; path: string; state: string }[];
  left_behind?: { what: string; why: string; size?: number | null }[];
  outside?: { path: string; size: number | null; tick: boolean; carryable: boolean }[];
  other_projects?: { path: string; project: string }[];
  tools?: { name: string; status: 'missing' | 'unchecked' }[];
  servers?: { command: string; port?: number }[];
}

export interface SendCheck {
  move: Verdict;
  copy: Verdict;
  fresh: Verdict;
  project_on_target: boolean;
  project_addable: Verdict;
  carry?: SendCarry;
  stop_shells?: number;
  running?: boolean;
}

export function reasonText(code: string | null | undefined): string {
  if (!code) return t('session.send.reason.unknown');
  const key = `session.send.reason.${code}`;
  const text = t(key);
  return text === key ? code.replace(/_/g, ' ') : text;
}

export function computerBlock(machine: PackMachine): string | null {
  const label = machine.label || machine.install_id.slice(0, 8);
  if (!machine.paired) return t('session.send.block.not_paired', { machine: label });
  if (machine.state !== 'connected') return t('session.send.block.offline', { machine: label });
  if (machine.snapshot?.restrictions && !machine.snapshot.restrictions.may_host_agents) {
    return t('session.send.block.no_hosting', { machine: label });
  }
  return null;
}

export function checkSend(sessionUuid: string, machine: string, stopRunning = false): Promise<SendCheck> {
  return authFetch<SendCheck>(`/sessions/${encodeURIComponent(sessionUuid)}/send/check`, {
    method: 'POST',
    body: JSON.stringify(stopRunning ? { machine, stop_running: true } : { machine }),
  });
}

export function postSend(
  sessionUuid: string,
  body: { machine: string; mode: SendMode; with_project: boolean; stop_running?: boolean },
): Promise<{ op_id: string; state: string; machine: string; mode: SendMode }> {
  return authFetch(`/sessions/${encodeURIComponent(sessionUuid)}/send`, { method: 'POST', body: JSON.stringify(body) });
}
