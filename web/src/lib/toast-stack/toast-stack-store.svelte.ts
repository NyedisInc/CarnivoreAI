import { toastSurface } from '../toast-surface';
import type { ToastStackManager, ToastView } from './types';

const EMPTY: ToastView = { cards: [], dismissAll: null, waiting: null, overflow: null };

let view = $state.raw<ToastView>(EMPTY);
let manager = $state.raw<ToastStackManager | null>(null);

export function currentView(): ToastView {
  return view;
}

export function currentManager(): ToastStackManager | null {
  return manager;
}

export function bindToastManager(host: object = globalThis): () => void {
  const found = toastSurface(host) as unknown as Partial<ToastStackManager> | null;
  if (!found || typeof found.subscribe !== 'function') {
    console.warn('[ToastStack] no ToastManager with a view to follow');
    return () => undefined;
  }
  const bound = found as ToastStackManager;
  manager = bound;
  const stop = bound.subscribe((next) => {
    view = next;
  });
  return () => {
    stop();
    manager = null;
    view = EMPTY;
  };
}
