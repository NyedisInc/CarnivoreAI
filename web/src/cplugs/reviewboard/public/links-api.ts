import { activeThemeId, ApiError, authFetch, t, themeTokens } from '../../sdk';

export const TTLS = ['1h', '1d', '7d'] as const;
export type Ttl = (typeof TTLS)[number];
export const MODES = ['pinned', 'follow'] as const;
export type Mode = (typeof MODES)[number];
export const ACCESSES = ['answer', 'read'] as const;
export type Access = (typeof ACCESSES)[number];

export interface LinkRow {
  id: string;
  board: string;
  revision: string;
  mode: Mode;
  access: Access;
  created_at: number;
  expires_at: number;
  revoked_at: number | null;
  status: 'active' | 'expired' | 'revoked';
  copyable: boolean;
}

export interface MintedLink {
  token: string;
  link: LinkRow;
}

export function isTtl(value: string): value is Ttl {
  return TTLS.some((known) => known === value);
}

export function isAccess(value: string): value is Access {
  return ACCESSES.some((known) => known === value);
}

export function ownerPalette(): Record<string, string> | null {
  const id = activeThemeId();
  const tokens = id ? themeTokens(id) : null;
  return tokens ? fitPalette(tokens) : null;
}

export const PALETTE_MAX_VARS = 600;
export const PALETTE_MAX_BYTES = 48 * 1024 - 256;

export function fitPalette(vars: Record<string, string>): Record<string, string> {
  const kept: Record<string, string> = {};
  let size = 2;
  let count = 0;
  for (const [name, value] of Object.entries(vars)) {
    if (count >= PALETTE_MAX_VARS) break;
    if (!name.startsWith('--oc-')) continue;
    const entry = JSON.stringify({ [name]: value }).length - 1;
    if (size + entry > PALETTE_MAX_BYTES) break;
    kept[name] = value;
    size += entry;
    count += 1;
  }
  return kept;
}

export function isMode(value: string): value is Mode {
  return MODES.some((known) => known === value);
}

const LINKS = '/cplugs/reviewboard/public/links';

export function mintLink(board: string, ttl: Ttl, mode: Mode, access: Access = 'answer', theme: Record<string, string> | null = null): Promise<MintedLink> {
  return authFetch<MintedLink>(LINKS, { method: 'POST', body: JSON.stringify({ board, ttl, mode, access, ...(theme ? { theme } : {}) }) });
}

export async function listLinks(board: string): Promise<LinkRow[]> {
  const out = await authFetch<{ links: LinkRow[] }>(`${LINKS}?board=${encodeURIComponent(board)}`);
  return out.links;
}

export async function fetchLinkToken(id: string): Promise<string> {
  const out = await authFetch<{ token: string }>(`${LINKS}/${encodeURIComponent(id)}/token`);
  return out.token;
}

export async function revokeLink(id: string): Promise<void> {
  await authFetch(`${LINKS}/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function revokeBoardLinks(board: string): Promise<number> {
  const out = await authFetch<{ revoked: number }>(`${LINKS}?board=${encodeURIComponent(board)}`, { method: 'DELETE' });
  return out.revoked;
}

export async function clearEndedLinks(board: string): Promise<number> {
  const out = await authFetch<{ cleared: number }>(`${LINKS}?board=${encodeURIComponent(board)}&ended=true`, { method: 'DELETE' });
  return out.cleared;
}

export async function publicHost(): Promise<string | null> {
  const row = await authFetch<{ settings?: Record<string, unknown> }>('/cplugs/reviewboard');
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
  if (!(error instanceof ApiError)) return t('cplug.reviewboard.public.share.failed');
  if (error.status === 403) return t('cplug.reviewboard.public.share.forbidden');
  if (error.code === 'publicboard_has_secret') return t('cplug.reviewboard.public.share.secret', { detectors: detectorNames(error.payload).join(', ') });
  return error.message.toLowerCase();
}
