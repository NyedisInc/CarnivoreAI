import type { ItemKind } from './api';

let draftOwner: string | null = null;

export function ownWidgetSettingsAs(draftId: string): void {
  draftOwner = draftId;
}

export function settingsOwner(kind: ItemKind, id: string): string {
  return kind === 'widget' && draftOwner !== null ? draftOwner : id;
}
