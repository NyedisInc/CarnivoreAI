
export type ToastCard = Record<string, unknown>;

export interface ToastManagerLike {
  add(card: ToastCard): void;
  dismiss?(id: string, options?: { syncToServer?: boolean }): unknown;
  pruneHidden?(shows: (card: { notify_type?: unknown }) => boolean): void;
}

export function toastSurface(host: object = globalThis): ToastManagerLike | null {
  const found = (host as { ToastManager?: ToastManagerLike }).ToastManager;
  return found && (typeof found.add === 'function' || typeof found.pruneHidden === 'function') ? found : null;
}

export function addLocalToast(card: ToastCard): boolean {
  const surface = toastSurface();
  if (!surface || typeof surface.add !== 'function') return false;
  surface.add(card);
  return true;
}
