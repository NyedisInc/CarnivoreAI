
import type { SlotId } from '../../engine/types';
import { manifestForSlot } from '../core-manifests';
import { hasInstanceSettings } from '../instance-settings';

export type WidgetOverlayKind = 'settings' | 'info';

export const configureSheet = $state<{ slot: SlotId | null; kind: WidgetOverlayKind }>({ slot: null, kind: 'settings' });

/* the settings overlay */
export function openConfigure(slot: SlotId): void {
  configureSheet.kind = 'settings';
  configureSheet.slot = slot;
}

export function closeConfigure(): void {
  configureSheet.slot = null;
}

export function isConfigurable(slot: SlotId): boolean {
  const manifest = manifestForSlot(slot);
  if (!manifest) return false;
  const fields = manifest.settings ? Object.keys(manifest.settings.fields).length : 0;
  return fields > 0 || hasInstanceSettings(manifest);
}
