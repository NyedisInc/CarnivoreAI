import { authFetch } from '../../opscenter/api/auth.svelte';
import { t } from '../i18n/index.svelte';
import type { CopyStatus, RemovedCopy } from './removed-logins';

export const GITHUB_APPS_URL = 'https://github.com/settings/applications';

export type SignInSeen = 'not_started' | 'not_checkable' | 'other_account' | 'seen' | 'not_seen';
export type SignInEnds = 'unknown' | 'keeps' | 'ends';

export type RotateCopy = Pick<RemovedCopy, 'status' | 'expires_at' | 'killed_at' | 'ended_by'> & { install_id: string; label?: string | null };

export interface RotateAccount {
  account: string;
  name: string;
  provider: 'claude' | 'codex';
  sign_in: 'app' | 'terminal';
  started_at: number | null;
  sign_in_seen: SignInSeen;
  sign_in_ends: SignInEnds;
  copies: RotateCopy[];
}

export interface RotateUnlisted { account: string; provider: 'claude' | 'codex'; copies: RotateCopy[] }

export interface RotateState {
  accounts: RotateAccount[];
  argent: { known: boolean; copies: RotateCopy[] };
  removed_computers: number;
  unlisted: RotateUnlisted[];
  not_tracked: string[];
}

export type ArgentState = 'none' | 'dead' | 'pending' | 'expired' | 'unavailable';

export const readRotate = (): Promise<RotateState> => authFetch<RotateState>('/pack/rotate');

export const startRotate = (account: string): Promise<{ account: string; started_at: number; sign_in_seen: SignInSeen }> =>
  authFetch('/pack/rotate/start', { method: 'POST', body: JSON.stringify({ account }) });

export const cancelArgent = (): Promise<{ computers: { install_id: string; state: ArgentState }[] }> => authFetch('/pack/rotate/argent', { method: 'POST' });

export const SEEN_LOOK: Readonly<Record<SignInSeen, { shape: string; tone: string }>> = {
  seen: { shape: 'filled', tone: 'ok' }, not_seen: { shape: 'hollow', tone: 'warn' }, not_started: { shape: 'hollow', tone: 'warn' },
  not_checkable: { shape: 'tri', tone: 'warn' }, other_account: { shape: 'tri', tone: 'warn' },
};

export const seenWords = (seen: SignInSeen): string => t(`pack.rotate.seen.${seen}`);

export const endsWords = (ends: SignInEnds): string => t(`pack.rotate.ends.${ends}`);

export const cancellable = (status: CopyStatus): boolean => status === 'dies_by' || status === 'expiry_unknown';

export function cancelWords(states: ArgentState[]): string[] {
  return (['dead', 'pending', 'expired', 'none', 'unavailable'] as const).filter((s) => states.includes(s)).map((s) => t(`pack.rotate.argent.state.${s}`));
}

export function namesProvider(name: string, provider: string): boolean {
  return name.toLowerCase().split(/[^a-z0-9]+/).includes(provider);
}
