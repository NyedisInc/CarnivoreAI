import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import type { PackOp } from './op-text';

export const PACK_OPS_POLL_MS = 5000;
const DISMISSED_KEY = 'carnivore.packOps.dismissed';
const DISMISSED_MAX = 60;

export const packOps: Resource<{ ops: PackOp[] }> = resource<{ ops: PackOp[] }>(() => authFetch<{ ops: PackOp[] }>('/pack/ops'), {
  intervalMs: PACK_OPS_POLL_MS, name: 'pack-ops', topics: ['pack_ops'],
});

function readDismissed(): string[] {
  try {
    const raw = JSON.parse(globalThis.localStorage?.getItem(DISMISSED_KEY) ?? '[]');
    return Array.isArray(raw) ? raw.filter((x): x is string => typeof x === 'string') : [];
  } catch {
    return [];
  }
}

export const view = $state({ dismissed: readDismissed(), cancelling: {} as Record<string, boolean>, note: {} as Record<string, string>, folded: {} as Record<string, boolean>, details: {} as Record<string, boolean> });

function writeDismissed(): void {
  view.dismissed = view.dismissed.slice(-DISMISSED_MAX);
  try {
    globalThis.localStorage?.setItem(DISMISSED_KEY, JSON.stringify(view.dismissed));
  } catch {
  }
}

export function shownOps(): PackOp[] {
  return (packOps.data?.ops ?? []).filter((o) => !view.dismissed.includes(o.id));
}

export function dismiss(id: string): void {
  const op = packOps.data?.ops.find((o) => o.id === id);
  if (op?.running && !op.interrupted) return;
  if (!view.dismissed.includes(id)) view.dismissed = [...view.dismissed, id];
  writeDismissed();
}

export function track(): Promise<void> {
  return packOps.refresh(true);
}

export async function reveal(id: string): Promise<void> {
  view.dismissed = view.dismissed.filter((x) => x !== id);
  view.folded = { ...view.folded, [id]: false };
  writeDismissed();
  await track();
}

function reasonOf(error: unknown): string {
  if (error instanceof ApiError) {
    const body = (error.payload as { detail?: unknown } | null)?.detail;
    if (body && typeof body === 'object' && typeof (body as { detail?: unknown }).detail === 'string') return (body as { detail: string }).detail;
    if (error.message) return error.message;
  }
  return t('pack.op.cancel_failed');
}

export async function cancelOp(id: string): Promise<void> {
  if (view.cancelling[id]) return;
  view.cancelling = { ...view.cancelling, [id]: true };
  view.note = { ...view.note, [id]: '' };
  try {
    await authFetch(`/pack/ops/${encodeURIComponent(id)}/cancel`, { method: 'POST' });
  } catch (error) {
    view.note = { ...view.note, [id]: reasonOf(error) };
  } finally {
    view.cancelling = { ...view.cancelling, [id]: false };
    await track();
  }
}
