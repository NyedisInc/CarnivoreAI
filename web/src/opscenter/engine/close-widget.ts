import type { CellMeta, SlotId } from './types';
import type { LayoutStore } from './layout.svelte';
import { isInstanceId } from './meta';
import { hideWithFlight, removeWithReflow } from './FlyLayer.svelte';
import { removable, removeWidget } from '../layout-editor/editor.svelte';

export interface CloseContext {
  editing: boolean;
  from: DOMRect | null;
}

export function closeOffered(meta: Pick<CellMeta, 'closable'>, id: SlotId): boolean {
  return meta.closable !== false && removable(id);
}

export function closeWidget(store: LayoutStore, id: SlotId, context: CloseContext): void {
  if (!removable(id)) return;
  if (context.editing) {
    void removeWidget(id);
    return;
  }
  if (isInstanceId(id)) void removeWithReflow(store, id);
  else void hideWithFlight(store, id, context.from);
}
