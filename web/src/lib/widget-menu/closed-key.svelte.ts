import { untrack } from 'svelte';
import { declaredActionsFor, type DeclaredAction } from '../../opscenter/widgets/menu/declared-actions.svelte';
import type { WidgetCapability, WidgetManifest } from '../../opscenter/widgets/types';

export const CLOSED_KEY_RUN_WAIT_MS = 3000;

const LIVE_PANE_CAPABILITIES: readonly WidgetCapability[] = ['terminal-input', 'browser-control'];

const drawn = $state<Record<string, number>>({});

export function noteDrawn(key: string): () => void {
  untrack(() => (drawn[key] = (drawn[key] ?? 0) + 1));
  return () =>
    untrack(() => {
      const left = (drawn[key] ?? 1) - 1;
      if (left > 0) drawn[key] = left;
      else delete drawn[key];
    });
}

export function bodyDrawn(key: string): boolean {
  return (drawn[key] ?? 0) > 0;
}

export function mountsUnseen(manifest: Pick<WidgetManifest, 'keepAlive' | 'capabilities'>): boolean {
  return !manifest.keepAlive && !manifest.capabilities.some((one) => LIVE_PANE_CAPABILITIES.includes(one));
}

export function runWhenDrawn(key: string, id: string, wait: number = CLOSED_KEY_RUN_WAIT_MS): void {
  let done = false;
  const stop = $effect.root(() => {
    $effect(() => {
      if (done || !bodyDrawn(key)) return;
      const action = declaredActionsFor(key).find((one) => one.id === id);
      if (!action) return;
      done = true;
      queueMicrotask(finish);
      untrack(() => action.run());
    });
  });
  const timer = setTimeout(() => {
    if (!done) console.warn('widget menu: the opened panel never declared the chosen action', { key, id, wait_ms: wait });
    finish();
  }, wait);
  function finish(): void {
    done = true;
    clearTimeout(timer);
    stop();
  }
}

export function openingActions(actions: readonly DeclaredAction[], key: string, open: () => void): DeclaredAction[] {
  return actions.map((action) => ({
    ...action,
    run: () => {
      open();
      runWhenDrawn(key, action.id);
    },
  }));
}
