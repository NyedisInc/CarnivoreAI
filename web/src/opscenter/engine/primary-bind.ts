
import { kindOf } from './meta';
import { sessionForSlot } from './slot-identity';
import { sessions } from '../api';
import { instancesOf } from './model';
import type { LayoutStore } from './layout.svelte';

export const PRIMARY_BIND_EVENT = 'cloude:primary-session-bound';

export function duplicatesOf(store: LayoutStore, sessionId: string): string[] {
  const id = (sessionId ?? '').trim();
  if (!id) return [];
  return instancesOf(store.state.layout).filter(
    (slot) => kindOf(slot) === 'terminal' && sessionForSlot(slot, sessions.data) === id,
  );
}

export function reconcilePrimaryBind(store: LayoutStore, sessionId: string): number {
  if (store.page !== 'terminal') return 0;
  const doomed = duplicatesOf(store, sessionId);
  for (const slot of doomed) store.remove(slot as never);
  return doomed.length;
}

export type BindClaim = (sessionId: string, tmuxName: string, tmuxEpoch: number | null) => boolean | 'hold';

let claim: BindClaim | null = null;

export function setBindClaim(fn: BindClaim): () => void {
  claim = fn;
  return () => {
    if (claim === fn) claim = null;
  };
}

export function bindPrimary(
  store: LayoutStore,
  sessionId: string,
  tmuxName: string,
  tmuxEpoch: number | null = null,
): number {
  if (store.page !== 'terminal') return 0;
  const kept = claim?.(sessionId ?? '', tmuxName ?? '', tmuxEpoch) ?? false;
  if (kept === 'hold') return 0;
  if (kept) return reconcilePrimaryBind(store, sessionId);
  store.bindSession(tmuxName, tmuxEpoch);
  return reconcilePrimaryBind(store, sessionId);
}

export function watchPrimaryBind(
  store: LayoutStore,
  target: EventTarget | null = (globalThis as { addEventListener?: unknown }).addEventListener
    ? (globalThis as unknown as EventTarget)
    : null,
): () => void {
  if (!target) return () => {};
  const onBind = (event: Event): void => {
    const detail = (event as CustomEvent<{ sessionId?: string; tmuxName?: string; tmuxEpoch?: number | null }>)
      .detail;
    bindPrimary(store, detail?.sessionId ?? '', detail?.tmuxName ?? '', detail?.tmuxEpoch ?? null);
  };
  target.addEventListener(PRIMARY_BIND_EVENT, onBind);
  return () => target.removeEventListener(PRIMARY_BIND_EVENT, onBind);
}
