/* the glance area */

import { beginGesture, captureRows, pickTarget } from '../engine/pointer';
import type { DropTarget, LayoutStore } from '../engine/layout.svelte';
import type { LayoutPage, SlotId } from '../engine/types';
import { CARD_THRESHOLD, insideBox, surfaceRoot } from './drawer-drag';
import { zoneDrag, zoneIndexAt } from '../../lib/drawer-zone/zone-drag.svelte';
import { glanceDrag, glanceIndexAt } from '../../lib/drawer-zone/glance-drag.svelte';
import { aimAtRails, clearRailAims, clearRailDrops, liftRails } from '../../lib/session-rail/rail-store.svelte';
import { isRepeatable } from '../../lib/drawer-zone/zone-model';
import type { RailEdge } from '../../lib/session-rail/rail-model';
import type { RailSpot } from '../../lib/session-rail/rail-sections';
import type { WidgetManifest } from '../widgets/types';
import { refusalWords, type GroupInputs } from './drawer-groups';

export interface SidebarOffer {
  refusal: string;
  moves: string | null;
}

export interface CarryOffer {
  surface: { cell: SlotId; refusal: string } | null;
  zone: SidebarOffer;
  glance: SidebarOffer;
  rail?: SidebarOffer;
}

export interface SidebarHolds {
  zone: readonly string[];
  glance: readonly { id: string; widget: string }[];
  disabled: (widgetId: string) => boolean;
  /* the glance area */
  repeatable: (widgetId: string) => boolean;
  t: GroupInputs['t'];
}

/* the glance area */
export function sidebarOffers(manifest: WidgetManifest, title: string, holds: SidebarHolds): { zone: SidebarOffer; glance: SidebarOffer } {
  if (holds.disabled(manifest.id)) {
    const refusal = refusalWords(title, holds.t).sentence;
    return { zone: { refusal, moves: null }, glance: { refusal, moves: null } };
  }
  if (manifest.instancing !== 'singleton') return { zone: { refusal: '', moves: null }, glance: { refusal: '', moves: null } };
  const placed = holds.repeatable(manifest.id) ? undefined : holds.glance.find((placement) => placement.widget === manifest.id);
  return {
    zone: { refusal: '', moves: !isRepeatable(manifest.id) && holds.zone.includes(manifest.id) ? manifest.id : null },
    glance: { refusal: '', moves: placed?.id ?? null },
  };
}

export type CarryTarget =
  | { area: 'surface'; target: DropTarget }
  | { area: 'zone'; index: number; moves: string | null }
  | { area: 'rail'; edge: RailEdge; spot: RailSpot; moves: string | null }
  | { area: 'glance'; index: number; moves: string | null };

export interface CarryHandlers {
  onMove: (x: number, y: number, aimed: boolean) => void;
  onDrop: (target: CarryTarget) => void;
  onRefuse: (sentence: string) => void;
  onEnd: (lifted: boolean) => void;
}

interface Verdict {
  target: CarryTarget | null;
  refusal: string;
}

function clearAreas(store: LayoutStore): void {
  zoneDrag.index = null;
  zoneDrag.carrying = false;
  glanceDrag.index = null;
  glanceDrag.carrying = false;
  clearRailDrops();
  store.clearDrag();
}

export function beginDrawerCarry(
  card: HTMLElement,
  event: PointerEvent,
  offer: CarryOffer,
  store: LayoutStore,
  page: LayoutPage,
  drawer: HTMLElement | null,
  handlers: CarryHandlers,
): boolean {
  const doc = card.ownerDocument;
  const root = offer.surface ? surfaceRoot(page, doc) : null;
  const scroller = root?.closest<HTMLElement>('.oc-content') ?? null;
  let rows: ReturnType<typeof captureRows>['rows'] = [];
  let cells: ReturnType<typeof captureRows>['cells'] = [];
  let verdict: Verdict = { target: null, refusal: '' };

  const overSurface = (x: number, y: number): Verdict => {
    if (!root || !offer.surface) return { target: null, refusal: '' };
    if (!insideBox((scroller ?? root).getBoundingClientRect(), x, y)) return { target: null, refusal: '' };
    const contentY = scroller ? y - scroller.getBoundingClientRect().top + scroller.scrollTop : y;
    const target = pickTarget(rows, cells, contentY, x, null);
    if (!target) return { target: null, refusal: '' };
    if (offer.surface.refusal) return { target: null, refusal: offer.surface.refusal };
    return { target: { area: 'surface', target }, refusal: '' };
  };

  const judge = (x: number, y: number): Verdict => {
    zoneDrag.index = null;
    glanceDrag.index = null;
    store.drag.target = null;
    const railOffer = offer.rail ?? offer.zone;
    const rail = aimAtRails(x, y, { side: railOffer.moves, bottom: railOffer.moves }, doc);
    if (rail !== null) {
      if (railOffer.refusal) {
        clearRailAims();
        return { target: null, refusal: railOffer.refusal };
      }
      const spot: RailSpot = { section: rail.section, index: rail.index, split: rail.split };
      return { target: { area: 'rail', edge: rail.edge, spot, moves: railOffer.moves }, refusal: '' };
    }
    const glance = glanceIndexAt(x, y, offer.glance.moves, doc);
    if (glance !== null) {
      if (offer.glance.refusal) return { target: null, refusal: offer.glance.refusal };
      glanceDrag.index = glance;
      return { target: { area: 'glance', index: glance, moves: offer.glance.moves }, refusal: '' };
    }
    const zone = zoneIndexAt(x, y, offer.zone.moves, doc);
    if (zone !== null) {
      if (offer.zone.refusal) return { target: null, refusal: offer.zone.refusal };
      zoneDrag.index = zone;
      return { target: { area: 'zone', index: zone, moves: offer.zone.moves }, refusal: '' };
    }
    if (drawer && insideBox(drawer.getBoundingClientRect(), x, y)) return { target: null, refusal: '' };
    const screen = overSurface(x, y);
    if (screen.target?.area === 'surface') store.drag.target = screen.target.target;
    return screen;
  };

  return beginGesture(card, event, {
    threshold: CARD_THRESHOLD,
    onLift: () => {
      if (root) ({ rows, cells } = captureRows(store, root, scroller, scroller?.scrollTop ?? 0));
      zoneDrag.carrying = true;
      glanceDrag.carrying = true;
      liftRails((offer.rail ?? offer.zone).moves);
    },
    onMove: (_dx, _dy, move) => {
      verdict = judge(move.clientX, move.clientY);
      handlers.onMove(move.clientX, move.clientY, verdict.target !== null);
    },
    onDrop: () => {
      const { target, refusal } = verdict;
      clearAreas(store);
      if (target) handlers.onDrop(target);
      else if (refusal) handlers.onRefuse(refusal);
    },
    onEnd: (lifted) => {
      clearAreas(store);
      handlers.onEnd(lifted);
    },
  });
}
