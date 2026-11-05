import { createAreaDrag, indexInArea, ZONE_DRAG_THRESHOLD, type AreaDrag } from '../drawer-zone/zone-drag.svelte';
import { isRepeatable, zoneItemKey, type ZoneItem } from '../drawer-zone/zone-model';
import { beginGesture } from '../../opscenter/engine/pointer';
import { RAIL_EDGES, RAIL_MAX_ITEMS, RAIL_SPECS, type RailEdge } from './rail-model';
import { RailStore, saveRailWrites } from './rail-layout-store.svelte';
import { canSplitAt, type RailSpot } from './rail-sections';
import { keysEndOf, splitOffer, type SplitOffer } from './rail-aim';
import { createDragGhost, type DragGhost } from '../drag-preview/ghost';

const GHOST_STRIP: readonly string[] = ['data-zone-item', 'data-edit-badge'];

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
  split: number | null;
  onBox: boolean;
}

const sideAim: RailAimState = $state({ section: null, split: null, onBox: false });
const bottomAim: RailAimState = $state({ section: null, split: null, onBox: false });

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
  return { section: sections.length - 1, index: sections[sections.length - 1]?.length ?? 0, split: false };
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
    railAims[edge].split = null;
    railAims[edge].onBox = false;
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

const along = (axis: 'x' | 'y', x: number, y: number): number => (axis === 'y' ? y : x);

const spanOf = (axis: 'x' | 'y', box: DOMRect): { start: number; end: number } =>
  axis === 'y' ? { start: box.top, end: box.bottom } : { start: box.left, end: box.right };

function offerFor(section: HTMLElement, ghost: HTMLElement | null, axis: 'x' | 'y', x: number, y: number, skip: string | null): SplitOffer {
  const own = spanOf(axis, section.getBoundingClientRect());
  const follows = ghost !== null && ghost.dataset['railGhost'] === section.dataset['railSection'];
  const area = { start: own.start, end: follows ? spanOf(axis, ghost.getBoundingClientRect()).end : own.end };
  const ends = Array.from(section.querySelectorAll<HTMLElement>('[data-zone-item]'))
    .filter((item) => item.dataset['zoneItem'] !== skip)
    .map((item) => spanOf(axis, item.getBoundingClientRect()).end);
  return splitOffer(area, keysEndOf(ends), along(axis, x, y));
}

interface RailHit {
  spot: RailSpot;
  offer: number | null;
}

function aimAtRail(edge: RailEdge, x: number, y: number, skip: string | null, doc: Document): RailHit | null {
  const root = railDrags[edge].element(doc);
  if (!root || root.hidden) return null;
  const axis = RAIL_SPECS[edge].axis;
  const ghost = root.querySelector<HTMLElement>('[data-rail-ghost]');
  if (ghost && inside(ghost, x, y)) {
    const after = Number(ghost.dataset['railGhost']);
    return { spot: { section: after, index: 0, split: true }, offer: after };
  }
  const layout = railStores[edge].layout;
  for (const section of root.querySelectorAll<HTMLElement>('[data-rail-section]')) {
    const index = indexInArea(section, x, y, skip, axis);
    if (index === null) continue;
    const at = Number(section.dataset['railSection']);
    const offer = canSplitAt(layout, at, railCarry.key) ? offerFor(section, ghost, axis, x, y, skip) : null;
    if (offer === 'drop') return { spot: { section: at, index: 0, split: true }, offer: at };
    return { spot: { section: at, index, split: false }, offer: offer === 'offer' ? at : null };
  }
  return null;
}

export function aimAtRails(x: number, y: number, skips: Partial<Record<RailEdge, string | null>> = {}, doc: Document = document): ({ edge: RailEdge } & RailSpot) | null {
  clearRailAims();
  for (const edge of RAIL_EDGES) {
    const hit = aimAtRail(edge, x, y, skips[edge] ?? null, doc);
    if (!hit) continue;
    const { spot } = hit;
    railAims[edge].split = hit.offer;
    railAims[edge].onBox = spot.split;
    if (!spot.split) {
      railDrags[edge].state.index = spot.index;
      railAims[edge].section = spot.section;
    }
    return { edge, ...spot };
  }
  return null;
}

export function beginRailItemDrag(from: RailEdge, handle: HTMLElement, event: PointerEvent, key: string, onRemoved: () => void): boolean {
  let aimed: ({ edge: RailEdge } & RailSpot) | null = null;
  let ghost: DragGhost | null = null;
  const cell = handle.closest<HTMLElement>('[data-edit-cell]') ?? handle;
  const box = cell.getBoundingClientRect();
  const grab = { x: event.clientX - box.left, y: event.clientY - box.top };
  return beginGesture(handle, event, {
    threshold: ZONE_DRAG_THRESHOLD,
    onLift: () => {
      liftRails(key);
      ghost = createDragGhost(cell, { grab, mount: handle.closest<HTMLElement>('[data-session-rail]') ?? undefined, strip: GHOST_STRIP });
    },
    onMove: (_dx, _dy, move) => {
      aimed = aimAtRails(move.clientX, move.clientY, { [from]: key }, handle.ownerDocument);
      ghost?.move(move.clientX, move.clientY);
    },
    onDrop: () => {
      const target = aimed;
      clearRailDrops();
      if (!target) {
        if (railStores[from].remove(key)) onRemoved();
        return;
      }
      const item = railStores[from].items.find((one) => zoneItemKey(one) === key);
      if (item) placeInRail(target.edge, item.widget, { section: target.section, index: target.index, split: target.split }, item.target, item);
    },
    onEnd: () => {
      ghost?.destroy();
      ghost = null;
      clearRailDrops();
    },
  });
}
