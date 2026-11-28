import { authFetch } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import { agoText, clockText, dateText } from '../publish-page/format';

export type CopyStatus = 'dead_now' | 'dies_by' | 'expired' | 'expiry_unknown';

export interface RemovedCopy {
  kind: 'claude' | 'codex' | 'argent';
  account: string | null;
  status: CopyStatus;
  expires_at: number | null;
  killed_at: number | null;
  ended_by?: 'argent_204' | 'sign_in' | null;
}

export interface RemovedComputer {
  install_id: string;
  removed_at: number;
  state: string;
  label?: string | null;
  copies: RemovedCopy[];
}

export interface RemovedLogins {
  computers: RemovedComputer[];
  argent_known: boolean;
  not_tracked: string[];
}

export const readRemovedLogins = (): Promise<RemovedLogins> => authFetch<RemovedLogins>('/pack/removed-logins');

export function statusNow(copy: Pick<RemovedCopy, 'status' | 'expires_at'>, nowMs: number): CopyStatus {
  return copy.status === 'dies_by' && copy.expires_at !== null && copy.expires_at <= nowMs ? 'expired' : copy.status;
}

export function statusWords(copy: Pick<RemovedCopy, 'status' | 'expires_at'>, nowMs: number): string {
  const status = statusNow(copy, nowMs);
  if (status === 'dies_by') return t('pack.removed_logins.status.dies_by', { time: `${dateText(copy.expires_at, t)} ${clockText(copy.expires_at, t)}` });
  if (status === 'expired') return t('pack.removed_logins.status.expired', { time: agoText(copy.expires_at, nowMs, t) });
  return t(`pack.removed_logins.status.${status}`);
}

export const STATUS_LOOK: Readonly<Record<CopyStatus, { shape: string; tone: string }>> = {
  dead_now: { shape: 'filled', tone: 'ok' }, expired: { shape: 'filled', tone: 'ok' }, dies_by: { shape: 'hollow', tone: 'warn' }, expiry_unknown: { shape: 'tri', tone: 'warn' },
};
