import { createAreaDrag, indexInArea, ZONE_DRAG_THRESHOLD, type AreaDrag } from '../drawer-zone/zone-drag.svelte';
import { isRepeatable, zoneItemKey, type ZoneItem } from '../drawer-zone/zone-model';
import { beginGesture } from '../../opscenter/engine/pointer';
import { RAIL_EDGES, RAIL_MAX_ITEMS, RAIL_SPECS, type RailBand, type RailEdge } from './rail-model';
import { RailStore, saveRailWrites } from './rail-layout-store.svelte';
import type { RailSpot } from './rail-sections';

export const railStores: Readonly<Record<RailEdge, RailStore>> = {
  side: new RailStore({ field: RAIL_SPECS.side.field, defaults: RAIL_SPECS.side.defaults, max: RAIL_MAX_ITEMS }),
  bottom: new RailStore({ field: RAIL_SPECS.bottom.field, defaults: RAIL_SPECS.bottom.defaults, max: RAIL_MAX_ITEMS }),
};

export const railDrags: Readonly<Record<RailEdge, AreaDrag>> = {
  side: createAreaDrag(RAIL_SPECS.side.id, RAIL_SPECS.side.axis),
  bottom: createAreaDrag(RAIL_SPECS.bottom.id, RAIL_SPECS.bottom.axis),
};

export interface RailAimState {
  section: number | null;
  band: RailBand | null;
}

const sideAim: RailAimState = $state({ section: null, band: null });
const bottomAim: RailAimState = $state({ section: null, band: null });

export const railAims: Readonly<Record<RailEdge, RailAimState>> = { side: sideAim, bottom: bottomAim };

export const railCarry = $state({ key: null as string | null });

export const sessionRail = railStores.side;

export const railDrag = railDrags.side;

export function otherEdge(edge: RailEdge): RailEdge {
  return edge === 'side' ? 'bottom' : 'side';
}

export function railHolding(key: string): RailEdge | null {
  return RAIL_EDGES.find((edge) => railStores[edge].items.some((item) => zoneItemKey(item) === key)) ?? null;
}

export function railEnd(edge: RailEdge): RailSpot {
  const sections = railStores[edge].sections;
  return { section: sections.length - 1, index: sections[sections.length - 1]?.length ?? 0, split: null };
}

export function placeInRail(edge: RailEdge, widget: string, spot: RailSpot = railEnd(edge), target?: string, moved?: ZoneItem): boolean {
  if (moved) {
    const from = otherEdge(edge);
    const comes = railStores[from].items.some((item) => zoneItemKey(item) === zoneItemKey(moved));
    if (comes) {
      const left = railStores[from].stageRemove(zoneItemKey(moved));
      const placed = railStores[edge].stagePlace(spot, widget, target, moved.instance ?? null, moved);
      void saveRailWrites([left, placed]);
      return left !== null || placed !== null;
    }
    return railStores[edge].place(spot, widget, target, moved.instance ?? null);
  }
  if (isRepeatable(widget)) return railStores[edge].place(spot, widget, target);
  const left = railStores[otherEdge(edge)].stageRemove(zoneItemKey({ widget, target }));
  const placed = railStores[edge].stagePlace(spot, widget, target);
  void saveRailWrites([left, placed]);
  return left !== null || placed !== null;
}

export function liftRails(key: string | null): void {
  railCarry.key = key;
  for (const edge of RAIL_EDGES) railDrags[edge].state.carrying = true;
}

export function clearRailAims(): void {
  for (const edge of RAIL_EDGES) {
    railDrags[edge].state.index = null;
    railAims[edge].section = null;
    railAims[edge].band = null;
  }
}

export function clearRailDrops(): void {
  clearRailAims();
  railCarry.key = null;
  for (const edge of RAIL_EDGES) railDrags[edge].state.carrying = false;
}

function inside(el: Element, x: number, y: number): boolean {
  const box = el.getBoundingClientRect();
  return x >= box.left && x <= box.right && y >= box.top && y <= box.bottom;
}

function aimAtRail(edge: RailEdge, x: number, y: number, skip: string | null, doc: Document): RailSpot | null {
  const root = railDrags[edge].element(doc);
  if (!root || root.hidden) return null;
  for (const section of root.querySelectorAll<HTMLElement>('[data-rail-section]')) {
    const index = indexInArea(section, x, y, skip, RAIL_SPECS[edge].axis);
    if (index !== null) return { section: Number(section.dataset['railSection']), index, split: null };
  }
  for (const band of root.querySelectorAll<HTMLElement>('[data-rail-band]')) {
    if (inside(band, x, y)) return { section: 0, index: 0, split: band.dataset['railBand'] === 'start' ? 'start' : 'end' };
  }
  return null;
}

export function aimAtRails(x: number, y: number, skips: Partial<Record<RailEdge, string | null>> = {}, doc: Document = document): ({ edge: RailEdge } & RailSpot) | null {
  clearRailAims();
  for (const edge of RAIL_EDGES) {
    const spot = aimAtRail(edge, x, y, skips[edge] ?? null, doc);
    if (!spot) continue;
    if (spot.split) railAims[edge].band = spot.split;
    else {
      railDrags[edge].state.index = spot.index;
      railAims[edge].section = spot.section;
    }
    return { edge, ...spot };
  }
  return null;
}

export function beginRailItemDrag(from: RailEdge, handle: HTMLElement, event: PointerEvent, key: string, onRemoved: () => void): boolean {
  let aimed: ({ edge: RailEdge } & RailSpot) | null = null;
  return beginGesture(handle, event, {
    threshold: ZONE_DRAG_THRESHOLD,
    onLift: () => liftRails(key),
    onMove: (_dx, _dy, move) => {
      aimed = aimAtRails(move.clientX, move.clientY, { [from]: key }, handle.ownerDocument);
    },
    onDrop: () => {
      const target = aimed;
      clearRailDrops();
      if (!target) return;
      const item = railStores[from].items.find((one) => zoneItemKey(one) === key);
      if (item) placeInRail(target.edge, item.widget, { section: target.section, index: target.index, split: target.split }, item.target, item);
    },
    onEnd: (lifted) => {
      const over = aimed !== null;
      clearRailDrops();
      if (lifted && !over && railStores[from].remove(key)) onRemoved();
    },
  });
}
