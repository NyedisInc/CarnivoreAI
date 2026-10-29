
export interface BoardAttachment {
  file_id: string;
  item_id: number;
  message_id: number;
  name: string;
  mime: string;
  bytes: number;
  sha256: string;
  added_at: string;
  revision: string | null;
  url: string | null;
}

export interface AttachmentList {
  slug: string;
  attachments: BoardAttachment[];
}

const API_PREFIX = '/api/v1';
const FILE_ROUTE = /^\/api\/v1\/cplugs\/huddle\/items\/\d+\/files\/[0-9a-f]{8}$/;

export function apiPathOf(url: string | null): string | null {
  if (!url || !FILE_ROUTE.test(url)) return null;
  return url.slice(API_PREFIX.length);
}

const INLINE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'application/pdf', 'text/plain']);

export function openType(mime: string): string | null {
  const bare = (mime.split(';')[0] ?? '').trim().toLowerCase();
  if (INLINE_TYPES.has(bare)) return bare;
  if (bare.startsWith('text/') || bare === 'application/json' || bare === 'image/svg+xml' || bare.endsWith('+xml') || bare.endsWith('/xml')) {
    return 'text/plain';
  }
  return null;
}

export function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} b`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} kb`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} mb`;
}

export function dateLabel(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  const two = (n: number): string => String(n).padStart(2, '0');
  return `${at.getFullYear()}-${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}
