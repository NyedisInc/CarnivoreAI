import { ApiError, authFetch, t } from '../sdk';

export const TTLS = ['1h', '1d', '7d'] as const;
export type Ttl = (typeof TTLS)[number];
export const MODES = ['pinned', 'follow'] as const;
export type Mode = (typeof MODES)[number];

export interface LinkRow {
  id: string;
  board: string;
  revision: string;
  mode: Mode;
  created_at: number;
  expires_at: number;
  revoked_at: number | null;
  status: 'active' | 'expired' | 'revoked';
}

export interface MintedLink {
  token: string;
  link: LinkRow;
}

export function isTtl(value: string): value is Ttl {
  return TTLS.some((known) => known === value);
}

export function isMode(value: string): value is Mode {
  return MODES.some((known) => known === value);
}

const LINKS = '/cplugs/publicboard/links';

export function mintLink(board: string, ttl: Ttl, mode: Mode): Promise<MintedLink> {
  return authFetch<MintedLink>(LINKS, { method: 'POST', body: JSON.stringify({ board, ttl, mode }) });
}

export async function listLinks(board: string): Promise<LinkRow[]> {
  const out = await authFetch<{ links: LinkRow[] }>(`${LINKS}?board=${encodeURIComponent(board)}`);
  return out.links;
}

export async function revokeLink(id: string): Promise<void> {
  await authFetch(`${LINKS}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function revokeBoardLinks(board: string): Promise<number> {
  const out = await authFetch<{ revoked: number }>(`${LINKS}?board=${encodeURIComponent(board)}`, { method: 'DELETE' });
  return out.revoked;
}

export async function publicHost(): Promise<string | null> {
  const row = await authFetch<{ settings?: Record<string, unknown> }>('/cplugs/publicboard');
  const raw = row.settings?.['hostnames'];
  const names = typeof raw === 'string' ? raw.split(',').map((item) => item.trim()).filter(Boolean) : [];
  return names[0] ?? null;
}

export function linkUrl(host: string, token: string): string {
  return `https://${host}/#${token}`;
}

function detectorNames(payload: unknown): string[] {
  if (!isRecord(payload) || !isRecord(payload['detail'])) return [];
  const found = payload['detail']['detectors'];
  return isRecord(found) ? Object.keys(found).sort() : [];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function refusalReason(error: unknown): string {
  if (!(error instanceof ApiError)) return t('cplug.publicboard.share.failed');
  if (error.status === 403) return t('cplug.publicboard.share.forbidden');
  if (error.code === 'publicboard_has_secret') return t('cplug.publicboard.share.secret', { detectors: detectorNames(error.payload).join(', ') });
  return error.message.toLowerCase();
}
