import { META, instanceId } from '../meta';
import { takenSlots } from '../components-actions';
import type { LayoutStore } from '../layout.svelte';
import { addInstance, showCell } from '../model';
import { pageSlotFor } from '../page-tabs';
import { tabsFor } from '../tab-groups.svelte';
import { freeSlot } from '../tab-split';
import { tabName } from '../tabs-motion/tab-name';
import type { InstanceKind, Layout, SlotId } from '../types';

export interface Pending {
  id: SlotId;
  layout: Layout;
  tab?: string;
  ghost?: { label: string; w: number; h: number };
  asMove?: boolean;
}

export const TAB_KIND = 'tab:';

const SESSION_KINDS: readonly string[] = ['terminal', 'browser'];

export function pendingFor(layout: Layout, kind: string, primary: string, store?: LayoutStore): Pending | null {
  if (kind.startsWith(TAB_KIND)) return store ? pendingForTab(store, kind.slice(TAB_KIND.length)) : null;
  if (kind in META) {
    const id = kind as SlotId;
    const next = showCell(layout, id as never, META);
    return next === layout ? null : { id, layout: next };
  }
  if (SESSION_KINDS.includes(kind)) return null;
  const name = `w${Date.now().toString(36)}`;
  const result = addInstance(layout, kind as InstanceKind, name, primary, META);
  return result.refusal ? null : { id: instanceId(kind as InstanceKind, name), layout: result.layout };
}

export function pendingForTab(store: LayoutStore, tab: string): Pending | null {
  const taken = takenSlots(store);
  const from = taken.find((slot) => tabsFor(store, slot).includes(tab)) ?? null;
  const source = from === null ? [] : tabsFor(store, from);
  if (from !== null && source.length === 1) return { id: from, layout: store.state.layout, tab, asMove: true };
  const everyTab = taken.flatMap((slot) => tabsFor(store, slot));
  const slot = pageSlotFor(tab, taken) ?? freeSlot(taken, [tab, ...source, ...everyTab]);
  if (!slot) return null;
  const result = addInstance(store.state.layout, 'terminal', slot.slice('terminal:'.length), '', META);
  if (result.refusal) return null;
  return { id: slot as SlotId, layout: result.layout, tab, ghost: { label: tabName(tab), w: 220, h: 96 } };
}
