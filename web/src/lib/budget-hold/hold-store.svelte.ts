import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import { addLocalToast } from '../toast-surface';

export interface HoldRow { item_id: string; item_name: string; session_keys: string[] }
interface HoldsPayload { enabled: boolean; holds: HoldRow[] }

export const holds: Resource<HoldsPayload> = resource<HoldsPayload>(
  () => authFetch<HoldsPayload>('/argent/holds'),
  { intervalMs: 60_000, name: 'argent-holds', demo: () => ({ enabled: false, holds: [] }), topics: ['argent_holds'] },
);

const refused = $state<Record<string, string>>({});
let started = false;

export function bannerItem(sessionId: string, rowId: number | null | undefined): string | null {
  const item = refused[sessionId];
  if (!item) return null;
  const rows = holds.data?.holds;
  if (rows && rowId != null && !rows.some((h) => h.session_keys.includes(String(rowId)))) return null;
  return item;
}

export function isRolloutItem(item: string): boolean {
  return !!holds.data?.holds.some((h) => h.item_name === item && h.item_id.startsWith('rollout:'));
}

export function holdText(item: string): string {
  return isRolloutItem(item) ? t('argent.rollout.hold') : t('argent.hold.banner', { item });
}

export function noteRefused(sessionId: string, item: string): void {
  refused[sessionId] = item;
  addLocalToast({
    id: `hold-${sessionId}-${Date.now()}`, session_id: null, kind: 'BudgetHold', title: t('argent.hold.toast'),
    body: holdText(item), session_label: t('argent.hold.surface'), local: true,
  });
}

export function startHoldFrames(): void {
  if (started || typeof window === 'undefined') return;
  started = true;
  window.addEventListener('carnivore:hold-refused', (event) => {
    const d = (event as CustomEvent<{ sessionId?: string; item?: string }>).detail;
    if (d?.sessionId && d.item) noteRefused(d.sessionId, d.item);
  });
}
