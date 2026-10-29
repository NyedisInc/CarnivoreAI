import { untrack, type Snippet } from 'svelte';
import type { SlotId } from '../../engine/types';

const panels = $state<Record<string, Snippet>>({});

export function declareSettingsPanel(slot: SlotId | string, panel: Snippet): () => void {
  untrack(() => {
    panels[slot] = panel;
  });
  return () => untrack(() => {
    if (panels[slot] === panel) delete panels[slot];
  });
}

export function settingsPanelFor(slot: SlotId | string): Snippet | null {
  return panels[slot] ?? null;
}
