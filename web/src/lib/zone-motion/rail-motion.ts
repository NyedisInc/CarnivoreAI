import { mountMeasured, type Stack } from './stack-motion';
import { aimRail, createRailAdapter, layoutRail, RAIL_PENDING, type RailAcross, type RailConfig, type RailGeometry } from './rail-adapter';
import type { Point } from '../motion-grid/types';
import type { RailSpot } from '../session-rail/rail-sections';

export interface RailMotionDeps extends Pick<RailConfig, 'cuts' | 'canSplit' | 'onLift' | 'onAim' | 'onEnd' | 'label'> {
  edge: string;
  axis: 'x' | 'y';
  sections(): readonly (readonly string[])[];
  place(key: string, spot: RailSpot, kind: string | null): void;
  leave(key: string, to: RailAcross | null): void;
}

const spotters = new Map<string, (client: Point, key: string) => { spot: RailSpot; offer: number | null } | null>();

export interface RailMotion {
  cell(node: HTMLElement, key: string): { update(key: string): void; destroy(): void };
  attach(container: HTMLElement): () => void;
  sync(): void;
  accept(kind: string, ev: PointerEvent): boolean;
}

function geometryOf(container: HTMLElement, axis: 'x' | 'y'): RailGeometry {
  const section = container.querySelector<HTMLElement>('[data-rail-keys]');
  const cs = section ? getComputedStyle(section) : null;
  const px = (v: string | undefined): number => Number.parseFloat(v ?? '') || 0;
  return {
    axis,
    length: axis === 'y' ? container.clientHeight : container.clientWidth,
    cross: axis === 'y' ? container.clientWidth : container.clientHeight,
    pad: axis === 'y' ? px(cs?.paddingTop) : px(cs?.paddingLeft),
    gap: px(axis === 'y' ? cs?.rowGap : cs?.columnGap),
  };
}

export function createRailMotion(deps: RailMotionDeps): RailMotion {
  const cells = new Map<HTMLElement, string>();
  const live = new Map<HTMLElement, { update(key: string): void; destroy(): void }>();
  let stack: Stack | null = null;
  let box: HTMLElement | null = null;
  let pending: { kind: string; node: HTMLElement; cell: { destroy(): void } } | null = null;

  const sections = (): (readonly string[])[] => {
    const list = deps.sections().map((keys) => [...keys]);
    if (list.length === 0) list.push([]);
    if (pending) list[list.length - 1]!.push(RAIL_PENDING);
    return list;
  };
  let stackSize: ((id: string) => { w: number; h: number }) | null = null;
  const size = (id: string): { w: number; h: number } => stackSize?.(id) ?? { w: 0, h: 0 };
  const origin = (): Point => {
    const r = box?.getBoundingClientRect();
    return { x: (r?.left ?? 0) - (box?.scrollLeft ?? 0), y: (r?.top ?? 0) - (box?.scrollTop ?? 0) };
  };

  const spotAt = (client: Point, key: string): { spot: RailSpot; offer: number | null } | null => {
    if (!box) return null;
    const r = box.getBoundingClientRect();
    if (client.x < r.left || client.x > r.right || client.y < r.top || client.y > r.bottom) return null;
    const geo = geometryOf(box, deps.axis);
    const list = sections();
    const rects = layoutRail(list, deps.cuts(), size, geo);
    const a = aimRail(list, deps.cuts(), rects, geo.length, deps.axis, deps.axis === 'y' ? client.y - r.top + box.scrollTop : client.x - r.left + box.scrollLeft, key, (s) => deps.canSplit(s, key));
    return { spot: { section: a.section, index: a.index, split: a.split }, offer: a.offer };
  };

  const clearPending = (): void => {
    if (!pending) return;
    pending.cell.destroy();
    pending.node.remove();
    pending = null;
    stack?.sync();
  };

  const config = (measure: (id: string) => { w: number; h: number }): RailConfig => {
    stackSize = measure;
    return {
      sections,
      cuts: deps.cuts,
      size: measure,
      geometry: () => (box ? geometryOf(box, deps.axis) : { axis: deps.axis, length: 0, cross: 0, pad: 0, gap: 0 }),
      canSplit: deps.canSplit,
      origin,
      across(client, key) {
        for (const [edge, spot] of spotters) {
          if (edge === deps.edge) continue;
          const at = spot(client, key);
          if (at) return { edge, ...at };
        }
        return null;
      },
      place: (key, spot, external) => deps.place(key, spot, external ? pending?.kind ?? null : null),
      leave: deps.leave,
      onLift: deps.onLift,
      onAim: deps.onAim,
      onEnd: deps.onEnd,
      label: deps.label,
    };
  };

  return {
    cell(node, key) {
      cells.set(node, key);
      node.setAttribute('data-motion-handle', '');
      const made = stack?.cell(node, key);
      if (made) live.set(node, made);
      return {
        update(next) {
          cells.set(node, next);
          live.get(node)?.update(next);
        },
        destroy() {
          cells.delete(node);
          live.get(node)?.destroy();
          live.delete(node);
        },
      };
    },
    attach(container) {
      box = container;
      stack = mountMeasured(container, (_items, measure) => createRailAdapter(config(measure)), { focusable: false });
      const off = stack.handle.on('dragend', () => clearPending());
      spotters.set(deps.edge, spotAt);
      for (const [node, key] of cells) live.set(node, stack.cell(node, key));
      return () => {
        off();
        clearPending();
        if (spotters.get(deps.edge) === spotAt) spotters.delete(deps.edge);
        live.clear();
        stack?.destroy();
        stack = null;
        box = null;
      };
    },
    sync: () => stack?.sync(),
    accept(kind, ev) {
      if (!stack || !box || pending) return false;
      const node = document.createElement('div');
      const inner = document.createElement('div');
      Object.assign(inner.style, {
        boxSizing: 'border-box',
        width: 'var(--rail-key-w,28px)',
        height: 'var(--rail-key-h,28px)',
        borderWidth: '1px',
        borderStyle: 'dashed',
        borderColor: 'var(--oc-cyan)',
        background: 'var(--oc-ground-titlerow)',
      });
      node.appendChild(inner);
      box.appendChild(node);
      pending = { kind, node, cell: stack.cell(node, RAIL_PENDING) };
      const w = inner.offsetWidth;
      const h = inner.offsetHeight;
      const taken = stack.handle.beginExternal({ id: RAIL_PENDING, rect: { x: 0, y: 0, w, h }, grab: { x: w / 2, y: h / 2 } }, ev);
      if (!taken) clearPending();
      return taken;
    },
  };
}
