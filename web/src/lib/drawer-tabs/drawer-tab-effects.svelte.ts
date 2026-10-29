/* nothing at all */
import { untrack } from 'svelte';
import { tabRegistry } from '../dynamic-tabs/registry';
import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { applyDrawerTab } from './drawer-tabs';

let stop: (() => void) | null = null;

export function startDrawerTabEffects(doc: Document = document): () => void {
  if (stop) return stop;
  sidebarTabs.reload();
  const end = $effect.root(() => {
    $effect(() => {
      const ids = sidebarTabs.present().map((def) => def.id);
      untrack(() => sidebarTabs.noteAppearances(ids));
    });
    $effect(() => applyDrawerTab(sidebarTabs.active(), tabRegistry.all(), doc));
  });
  stop = () => {
    end();
    stop = null;
  };
  return stop;
}
