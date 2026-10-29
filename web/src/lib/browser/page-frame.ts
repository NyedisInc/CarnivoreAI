
export const FRAMEABLE_APP_PATH = '/static/popout.html';
export const SANDBOXED_PATH_PREFIX = '/api/v1/';

export const APP_SANDBOX =
  'allow-scripts allow-same-origin allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-downloads';
export const ARTIFACT_SANDBOX = 'allow-scripts';

export type PageFrameKind = 'sandboxed' | 'app';

export interface PageInfo {
  id: string;
  key: string;
  frame: PageFrameKind;
  title: string;
  opened_at: number;
  src: string | null;
}

export interface FrameablePage {
  key: string;
  src: string;
  frame: PageFrameKind;
}

export function frameable(page: unknown): FrameablePage | null {
  const p = page as Partial<FrameablePage> | null;
  if (!p || typeof p.key !== 'string' || !p.key || typeof p.src !== 'string' || !p.src.startsWith('/') || p.src.startsWith('//')) return null;
  if (p.src.includes('\\')) return null;
  if (p.frame === 'sandboxed') return p.src.startsWith(SANDBOXED_PATH_PREFIX) ? { key: p.key, src: p.src, frame: 'sandboxed' } : null;
  if (p.frame !== 'app') return null;
  try {
    const base = globalThis.location?.origin ?? 'http://localhost';
    const url = new URL(p.src, base);
    return url.origin === base && url.pathname === FRAMEABLE_APP_PATH ? { key: p.key, src: p.src, frame: 'app' } : null;
  } catch {
    return null;
  }
}
