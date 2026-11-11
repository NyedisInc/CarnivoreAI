import type { Adapter, GestureState, ItemId, KeyStep, Point, Rect, Source, Target } from '../motion-grid/types';
import { halveAt } from '../session-rail/rail-cuts';
import { keysEndOf, splitOffer } from '../session-rail/rail-aim';
import type { RailSpot } from '../session-rail/rail-sections';
import { STACK_ID_ATTR } from './stack-adapter';

export interface RailGeometry {
  axis: 'x' | 'y';
  length: number;
  cross: number;
  pad: number;
  gap: number;
}

export interface RailAcross {
  edge: string;
  spot: RailSpot;
  offer: number | null;
}

export interface RailConfig {
  sections(): readonly (readonly string[])[];
  cuts(): readonly number[];
  size(id: ItemId): { w: number; h: number };
  geometry(): RailGeometry;
  canSplit(section: number, key: string | null): boolean;
  origin(): Point;
  across(client: Point, key: string): RailAcross | null;
  place(key: string, spot: RailSpot, external: boolean): void;
  leave(key: string, to: RailAcross | null): void;
  onLift(key: string | null): void;
  onAim(aim: { section: number | null; index: number | null; offer: number | null; onBox: boolean; across: RailAcross | null } | null): void;
  onEnd(): void;
  label?(id: ItemId): string;
}

export const RAIL_PENDING = '__pending';

interface Aim {
  section: number;
  index: number;
  split: boolean;
  offer: number | null;
}

type Payload = { kind: 'spot'; id: ItemId; spot: RailSpot; external: boolean } | { kind: 'out'; id: ItemId };

export function layoutRail(sections: readonly (readonly string[])[], cuts: readonly number[], size: (id: ItemId) => { w: number; h: number }, g: RailGeometry): Map<ItemId, Rect> {
  const out = new Map<ItemId, Rect>();
  const edges = [0, ...cuts, 1];
  sections.forEach((keys, s) => {
    let at = (edges[s] ?? 0) * g.length + g.pad;
    for (const id of keys) {
      const { w, h } = size(id);
      if (g.axis === 'y') {
        out.set(id, { x: (g.cross - w) / 2, y: at, w, h });
        at += h + g.gap;
      } else {
        out.set(id, { x: at, y: (g.cross - h) / 2, w, h });
        at += w + g.gap;
      }
    }
  });
  return out;
}

export function aimRail(
  sections: readonly (readonly string[])[], cuts: readonly number[], rects: ReadonlyMap<ItemId, Rect>, length: number, axis: 'x' | 'y',
  pos: number, skip: string | null, canSplit: (section: number) => boolean,
): Aim {
  const edges = [0, ...cuts, 1].map((edge) => edge * length);
  let section = sections.length - 1;
  for (let s = 0; s < sections.length; s++) {
    if (pos < edges[s + 1]!) {
      section = s;
      break;
    }
  }
  section = Math.max(0, section);
  const span = (id: ItemId): { start: number; end: number } => {
    const r = rects.get(id) ?? { x: 0, y: 0, w: 0, h: 0 };
    return axis === 'y' ? { start: r.y, end: r.y + r.h } : { start: r.x, end: r.x + r.w };
  };
  const others = (sections[section] ?? []).filter((id) => id !== skip);
  const index = others.filter((id) => (span(id).start + span(id).end) / 2 < pos).length;
  if (!canSplit(section)) return { section, index, split: false, offer: null };
  const offer = splitOffer({ start: edges[section] ?? 0, end: edges[section + 1] ?? length }, keysEndOf(others.map((id) => span(id).end)), pos);
  if (offer === 'drop') return { section, index: 0, split: true, offer: section };
  return { section, index, split: false, offer: offer === 'offer' ? section : null };
}

export function createRailAdapter(cfg: RailConfig): Adapter {
  const rectsNow = (): Map<ItemId, Rect> => layoutRail(cfg.sections(), cfg.cuts(), cfg.size, cfg.geometry());
  const clientOf = (p: Point): Point => {
    const o = cfg.origin();
    return { x: o.x + p.x, y: o.y + p.y };
  };
  const idOf = (g: GestureState): ItemId => (g.source as { id: ItemId }).id;
  const carried = (id: ItemId): string | null => (id === RAIL_PENDING ? null : id);
  const aimFor = (g: GestureState): Aim => {
    const geo = cfg.geometry();
    const id = idOf(g);
    return aimRail(cfg.sections(), cfg.cuts(), g.base, geo.length, geo.axis, geo.axis === 'y' ? g.pointer.y : g.pointer.x, id, (s) => cfg.canSplit(s, carried(id)));
  };
  const acrossFor = (g: GestureState): RailAcross | null => cfg.across(clientOf(g.pointer), idOf(g));

  return {
    rects: rectsNow,
    hit(el: Element): Source | null {
      const cell = el.closest<HTMLElement>(`[${STACK_ID_ATTR}]`);
      if (!cell) return null;
      const id = cell.getAttribute(STACK_ID_ATTR) as ItemId;
      return id === RAIL_PENDING ? null : { kind: 'move', id };
    },
    begin(source) {
      const id = (source as { id: ItemId }).id;
      cfg.onLift(carried(id));
    },
    targetKey(g) {
      if (g.outside) {
        const to = acrossFor(g);
        return to ? `out:${to.edge}:${to.spot.section}:${to.spot.index}:${to.spot.split ? 1 : 0}:${to.offer}` : 'out';
      }
      const a = aimFor(g);
      return `${a.section}:${a.index}:${a.split ? 1 : 0}:${a.offer}`;
    },
    preview(g, key) {
      const id = idOf(g);
      if (key.startsWith('out')) {
        const to = acrossFor(g);
        cfg.onAim({ section: null, index: null, offer: null, onBox: false, across: to });
        return { key, rects: new Map(g.base), landing: null, payload: { kind: 'out', id } satisfies Payload };
      }
      const a = aimFor(g);
      cfg.onAim({ section: a.section, index: a.split ? null : a.index, offer: a.offer, onBox: a.split, across: null });
      const sections = cfg.sections().map((keys) => keys.filter((k) => k !== id));
      let cuts = [...cfg.cuts()];
      if (a.split) {
        cuts = halveAt(cuts, a.section);
        sections.splice(a.section + 1, 0, [id]);
      } else {
        const list = sections[a.section] ?? [];
        list.splice(a.index, 0, id);
        sections[a.section] = list;
      }
      const rects = layoutRail(sections, cuts, cfg.size, cfg.geometry());
      const spot: RailSpot = { section: a.section, index: a.index, split: a.split };
      return { key, rects, payload: { kind: 'spot', id, spot, external: g.source.kind === 'external' } satisfies Payload };
    },
    commit(t, g) {
      const p = t.payload as Payload | undefined;
      cfg.onEnd();
      if (!p) return;
      if (p.kind === 'out') cfg.leave(p.id, g ? acrossFor(g) : null);
      else if (p.external || !sameSpot(cfg.sections(), p.id, p.spot)) cfg.place(p.id, p.spot, p.external);
    },
    cancel() {
      cfg.onEnd();
    },
    stepFromTarget: true,
    step(id: ItemId, step: KeyStep, from?: Target | null): Target | null {
      if (step.resize) return null;
      const geo = cfg.geometry();
      const dir: -1 | 1 | 0 = step.dir === (geo.axis === 'y' ? 'up' : 'left') ? -1 : step.dir === (geo.axis === 'y' ? 'down' : 'right') ? 1 : 0;
      if (dir === 0) return null;
      const sections = cfg.sections().map((keys) => keys.filter((k) => k !== id));
      const prev = from?.payload as Payload | undefined;
      const stored = cfg.sections().findIndex((keys) => keys.includes(id));
      const section = prev?.kind === 'spot' ? prev.spot.section : stored;
      const list = sections[section];
      if (!list || stored < 0) return null;
      const at = prev?.kind === 'spot' ? prev.spot.index! : cfg.sections()[stored]!.indexOf(id);
      const to = at + dir;
      if (to < 0 || to > list.length) return null;
      list.splice(to, 0, id);
      const spot: RailSpot = { section, index: to, split: false };
      return { key: `k${to}`, rects: layoutRail(sections, cfg.cuts(), cfg.size, geo), payload: { kind: 'spot', id, spot, external: false } satisfies Payload };
    },
    label: cfg.label,
  };
}

function sameSpot(sections: readonly (readonly string[])[], id: ItemId, spot: RailSpot): boolean {
  if (spot.split) return false;
  const list = sections[spot.section];
  return !!list && list.indexOf(id) === spot.index;
}
