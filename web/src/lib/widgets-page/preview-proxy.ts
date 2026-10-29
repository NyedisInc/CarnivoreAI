/* and writes nothing */
import { authFetch, ApiError } from '../../opscenter/api/auth.svelte';
import type { PreviewAnswer, PreviewRequest } from '../../widget-preview/protocol';

export const PROXY_SHARE_MS = 2000;

export type PreviewReader = (path: string) => Promise<unknown>;

interface Shared {
  at: number;
  read: Promise<unknown>;
}

export function createPreviewProxy(
  reader: PreviewReader = (path) => authFetch<unknown>(path),
  now: () => number = () => Date.now(),
): { answer: (request: PreviewRequest) => Promise<PreviewAnswer> } {
  const shared = new Map<string, Shared>();
  return {
    async answer(request: PreviewRequest): Promise<PreviewAnswer> {
      if (typeof request?.path !== 'string' || !request.path.startsWith('/')) {
        return { id: request?.id ?? 0, ok: false, status: 400, detail: 'not a path under /api/v1' };
      }
      const at = now();
      let entry = shared.get(request.path);
      if (!entry || at - entry.at > PROXY_SHARE_MS) {
        entry = { at, read: reader(request.path) };
        shared.set(request.path, entry);
      }
      try {
        return { id: request.id, ok: true, body: await entry.read };
      } catch (error) {
        const status = error instanceof ApiError ? error.status : 503;
        return { id: request.id, ok: false, status, detail: error instanceof Error ? error.message : String(error) };
      }
    },
  };
}
