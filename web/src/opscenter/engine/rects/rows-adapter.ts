import type { Adapter, GestureState, ItemId, Rect, Source, Target, Via } from '../../../lib/motion-grid';
import { t } from '../../../lib/i18n/index.svelte';
import { tearOffCell } from '../../../lib/tearoff/tearoff';
import { applyDrop } from '../drop';
import { buildZones, candidatesAt, compassAt, nextTarget, type Candidate, type Dragged, type Zones } from '../drop-grammar';
import type { CompassView } from '../dock-compass';
import type { DropTarget, LayoutStore } from '../layout.svelte';
import { META, metaFor } from '../meta';
import { PRIMARY_SLOT, removeCell } from '../model';
import type { CellDragMerge } from '../pointer';
import { placeOf, spanOf, visualOrder } from '../spans';
import { tabDrag } from '../tab-drag-state.svelte';
import { commitMerge, commitTabDrop, measureStrips, splitNeedsRow, swallowNextClick, type TabDrop } from '../tab-drag';
import { takeWake } from '../tabs-motion/carry';
import { tabName } from '../tabs-motion/tab-name';
import { tearOffTab } from '../../../lib/tearoff/tab-tearoff';
import type { Layout, SlotId } from '../types';
import { applyDivider, dividerSpecs, type DividerSpec } from './dividers';
import { buildSnapshot, sameRects, toDropTarget } from './drop-aim';
import { contentExtent, dropLeavesNothingWorse, layoutGeometry, rectsAreSound, type SurfaceGeometry } from './layout-rects';
import type { Pending } from './pending';

const NOGRAB = 'button, a, input, select, textarea, [contenteditable], [role="menu"], [data-motion-nograb]';

const GRAB = '.oc-frame-strip, .oc-frame-title';

const KEY_PX = 32;

export const DWELL_MS = 140;

export const REST_PX = 6;

const ARMED = '|a';

const GHOST = '@ghost';

export interface RowsAdapterDeps {
  store: LayoutStore;
  box(): { width: number; height: number };
  gutter: number;
  wide(): boolean;
  zoomed(): string | null;
  container(): HTMLElement | null;
  merge?(id: SlotId): CellDragMerge | undefined;
  onState(state: { preview: Layout | null; moving: boolean }): void;
  onCompass?(view: CompassView | null): void;
  onEnd?(): void;
  now?(): number;
}

interface Payload {
  layout: Layout;
  from: Layout;
}

interface TabPayload {
  drop: TabDrop;
}

interface MergePayload {
  merge: { from: string; into: string; index?: number };
}

interface Entry {
  offered: boolean;
  cand: Candidate;
  layout: Layout | null;
  rect: Rect | null;
  landing: Rect | null;
  armedRects: Map<string, Rect> | null;
  idleRects: Map<string, Rect> | null;
  tab: TabDrop | null;
  merge: MergePayload['merge'] | null;
}

export interface RowsAdapter extends Adapter {
  setPending(pending: Pending | null): void;
  geometry(): SurfaceGeometry;
}

export function createRowsAdapter(deps: RowsAdapterDeps): RowsAdapter {
  const { store, gutter } = deps;
  const clock = deps.now ?? ((): number => performance.now());
  let memo: { layout: Layout; w: number; h: number; geo: SurfaceGeometry } | null = null;
  let pending: Pending | null = null;
  let run: {
    from: Layout;
    base: Layout;
    start: SurfaceGeometry;
    specs: DividerSpec[];
    origin: { left: number; top: number };
    carried: string | null;
    ghost: boolean;
    active: SlotId;
    dragged: Dragged;
    zones: Zones | null;
    soundStart: boolean;
    refuseSplit: boolean;
    wake: (() => void) | undefined;
    entries: Map<string, Entry>;
    held: Candidate | null;
    since: number;
    rest: { x: number; y: number; at: number };
    armed: boolean;
    compassKey: string;
    torn: boolean;
    up: ((ev: PointerEvent) => void) | null;
  } | null = null;

  const geometryOf = (layout: Layout): SurfaceGeometry => {
    const { width, height } = deps.box();
    return layoutGeometry(layout, width, height, gutter);
  };

  const live = (): SurfaceGeometry => {
    const layout = store.state.layout;
    const { width, height } = deps.box();
    if (!memo || memo.layout !== layout || memo.w !== width || memo.h !== height) {
      memo = { layout, w: width, h: height, geo: layoutGeometry(layout, width, height, gutter) };
    }
    return memo.geo;
  };

  let carried: string | null = null;

  const finish = (): void => {
    if (run?.up) window.removeEventListener('pointerup', run.up, true);
    pending = null;
    tabDrag.tab = null;
    tabDrag.target = null;
    run = null;
    deps.onCompass?.(null);
    deps.onState({ preview: null, moving: false });
    deps.onEnd?.();
  };

  const unchanged = (key: string, valid = true): Target => ({
    key,
    rects: run?.start.rects ?? geometryOf(store.state.layout).rects,
    valid,
    landing: null,
  });

  const targetFor = (key: string, layout: Layout, from: Layout, active: SlotId | null, instant: boolean): Target => {
    const rects = geometryOf(layout).rects;
    return { key, rects, landing: active ? (rects.get(active) ?? null) : null, instant, payload: { layout, from } satisfies Payload };
  };

  const specOf = (id: string, specs: readonly DividerSpec[]): DividerSpec | undefined => specs.find((one) => one.id === id);

  const evaluate = (cand: Candidate): Entry => {
    const r = run!;
    const known = r.entries.get(cand.key);
    if (known) return known;
    const entry = build(r, cand);
    r.entries.set(cand.key, entry);
    return entry;
  };

  const build = (r: NonNullable<typeof run>, cand: Candidate): Entry => {
    const no: Entry = { offered: false, cand, layout: null, rect: null, landing: null, armedRects: null, idleRects: null, tab: null, merge: null };
    const target = cand.target;
    if (target.kind === 'strip' || target.kind === 'middle') {
      const into = r.start.rects.get(target.slot as SlotId);
      if (!into || (!r.ghost && (r.active === PRIMARY_SLOT || target.slot === r.active))) return no;
      const index = target.kind === 'strip' ? target.index : undefined;
      const tab: TabDrop = target.kind === 'strip' ? { kind: 'strip', slot: target.slot, index: target.index } : { kind: 'middle', slot: target.slot };
      const merge = { from: r.active, into: target.slot, index };
      if (r.ghost) return { ...no, offered: true, rect: into, landing: target.kind === 'middle' ? into : null, tab, merge };
      const surface = deps.box();
      const left = geometryOf(removeCell(r.base, r.active, surface.width, surface.height)).rects;
      const grown = left.get(target.slot as SlotId) ?? into;
      const armedRects = new Map<string, Rect>(left);
      armedRects.set(r.active, grown);
      return { ...no, offered: true, rect: grown, landing: target.kind === 'middle' ? grown : null, armedRects, tab, merge };
    }
    if (r.carried && r.refuseSplit) return no;
    const { width, height } = deps.box();
    const drop = toDropTarget(target, width, height);
    const layout = drop ? applyDrop(r.base, r.active, drop, META) : r.base;
    if (!drop || layout === r.base) return no;
    const geo = geometryOf(layout);
    const rect = geo.rects.get(r.active);
    if (!rect || sameRects(r.start.rects, geo.rects)) return no;
    if (r.soundStart && !rectsAreSound([...geo.rects.values()], width, height, gutter)) return no;
    if (!r.soundStart && (drop.kind === 'split' || drop.kind === 'stack') && !dropLeavesNothingWorse(r.start.rects, geo.rects, r.active, drop.of, drop.kind === 'split')) return no;
    const armedRects = new Map<string, Rect>(geo.rects);
    if (r.ghost) armedRects.set(GHOST, rect);
    return { ...no, offered: true, layout, rect, landing: rect, armedRects, tab: { kind: 'out', target: drop as DropTarget } };
  };

  const idleRects = (r: NonNullable<typeof run>, entry: Entry): Map<string, Rect> => {
    if (!entry.idleRects) {
      const rects = new Map<string, Rect>(r.start.rects);
      if (entry.rect) {
        rects.set(r.active, entry.rect);
        if (r.ghost) rects.set(GHOST, entry.rect);
      }
      entry.idleRects = rects;
    }
    return entry.idleRects;
  };

  const showCompass = (r: NonNullable<typeof run>, g: GestureState): void => {
    const geo = r.zones && !g.outside && (!r.held || r.held.compass) ? compassAt(r.zones, g.pointer, r.dragged) : null;
    const view: CompassView | null = geo
      ? {
          window: geo.window,
          plate: geo.plate,
          icons: geo.slots.map((s) => {
            const cand = s.allowed ? candidatesAt(r.zones!, { x: s.rect.x + s.rect.w / 2, y: s.rect.y + s.rect.h / 2 }, r.dragged).find((c) => c.compass === s.dir) : undefined;
            return { dir: s.dir, rect: s.rect, enabled: !!cand && evaluate(cand).offered, hot: !!cand && r.held?.key === cand.key };
          }),
        }
      : null;
    const key = view ? `${view.window}|${view.icons.map((i) => `${i.enabled ? 1 : 0}${i.hot ? 1 : 0}`).join('')}` : '';
    if (key === r.compassKey) return;
    r.compassKey = key;
    deps.onCompass?.(view);
  };

  const aim = (r: NonNullable<typeof run>, g: GestureState): string => {
    if (!r.zones) return 'none';
    if (g.outside) {
      r.held = null;
      r.armed = false;
      showCompass(r, g);
      return 'out';
    }
    let fresh: Candidate | null = null;
    for (const cand of candidatesAt(r.zones, g.pointer, r.dragged)) {
      if (evaluate(cand).offered) {
        fresh = cand;
        break;
      }
    }
    const next = nextTarget(r.held, fresh, g.pointer, r.armed && r.held ? evaluate(r.held).landing : null);
    const now = clock();
    if (next?.key !== r.held?.key) {
      r.held = next;
      r.since = now;
      r.armed = false;
      r.rest = { x: g.pointer.x, y: g.pointer.y, at: now };
    } else if (Math.hypot(g.pointer.x - r.rest.x, g.pointer.y - r.rest.y) > REST_PX) {
      r.rest = { x: g.pointer.x, y: g.pointer.y, at: now };
    }
    showCompass(r, g);
    const gap = !!r.held && r.held.reflows && !r.held.compass;
    const settled = now - (gap ? Math.max(r.since, r.rest.at) : r.since) >= DWELL_MS;
    if (r.held && !r.armed && (r.held.reflows || evaluate(r.held).armedRects) && settled) r.armed = true;
    return r.held ? r.held.key + (r.armed ? ARMED : '') : 'none';
  };

  return {
    rects() {
      const rects = new Map(live().rects);
      const zoomed = deps.zoomed();
      const { width, height } = deps.box();
      if (zoomed && rects.has(zoomed as SlotId)) rects.set(zoomed as SlotId, { x: 0, y: 0, w: width, h: height });
      return rects;
    },

    geometry: live,

    setPending(next) {
      pending = next;
    },

    extent() {
      return contentExtent(store.state.layout, live().tracks);
    },

    label(id: ItemId) {
      if (carried) return tabName(carried);
      const meta = metaFor(id as SlotId, META);
      return meta.titleName ?? t(meta.titleKey);
    },

    hit(el, ev): Source | null {
      void ev;
      if (!deps.wide() || deps.zoomed()) return null;
      const handle = el.closest<HTMLElement>('[data-abs-divider]');
      if (handle) return { kind: 'divider', id: handle.dataset['absDivider']! };
      if (!el.closest('[data-motion-grab]') && (el.closest(NOGRAB) || !el.closest(GRAB))) return null;
      const slot = el.closest<HTMLElement>('[data-abs-slot]')?.dataset['absSlot'];
      return slot ? { kind: 'move', id: slot } : null;
    },

    begin(source: Source, via: Via) {
      const from = store.snapshot();
      const external = source.kind === 'external';
      const asMove = pending?.asMove === true && (external || source.kind === 'move') && pending.id === source.id;
      const ghost = external && pending?.tab !== undefined && !pending.asMove;
      const base = external && pending ? pending.layout : from;
      const start = external ? from : base;
      const startGeo = geometryOf(start);
      const box = deps.box();
      const rect = deps.container()?.getBoundingClientRect();
      const tab = ghost || asMove ? (pending?.tab ?? null) : null;
      const active = (ghost && pending ? pending.id : source.id) as SlotId;
      const root = deps.container();
      carried = tab;
      const canMerge = tab !== null || (source.kind !== 'divider' && deps.merge?.(active) !== undefined);
      const aims = via !== 'keyboard' && source.kind !== 'divider';
      const origin = { left: rect?.left ?? 0, top: rect?.top ?? 0 };
      const zones = aims ? buildZones(buildSnapshot(startGeo, box, gutter, root ? measureStrips(root) : [], origin, canMerge)) : null;
      run = {
        from,
        base,
        start: startGeo,
        specs: dividerSpecs(base, geometryOf(base).tracks, box, gutter, true),
        origin,
        carried: tab,
        ghost,
        active,
        dragged: tab ? { kind: 'tab', tab } : { kind: 'window', id: active },
        zones,
        soundStart: aims && rectsAreSound([...startGeo.rects.values()], box.width, box.height, gutter),
        refuseSplit: tab !== null && splitNeedsRow(),
        wake: tab ? takeWake(tab) : undefined,
        entries: new Map(),
        held: null,
        since: 0,
        rest: { x: 0, y: 0, at: 0 },
        armed: false,
        compassKey: '',
        torn: false,
        up: null,
      };
      if (tab) tabDrag.tab = tab;
      if ((via === 'pointer' && source.kind === 'move') || tab) {
        const held = run;
        run.up = (ev: PointerEvent) => {
          held.torn = tab ? tearOffTab(tab, ev) : tearOffCell(source.id, ev);
        };
        window.addEventListener('pointerup', run.up, true);
      }
      deps.onState({ preview: null, moving: via !== 'keyboard' && source.kind !== 'divider' });
    },

    targetKey(g) {
      if (!run) return '';
      if (g.source.kind === 'divider') return `d:${Math.round(g.delta.x)}:${Math.round(g.delta.y)}`;
      return aim(run, g);
    },

    preview(g, key) {
      if (!run) return { key, rects: new Map() };
      if (g.source.kind === 'divider') {
        const spec = specOf(g.source.id, run.specs);
        const layout = spec ? applyDivider(run.base, spec, g.delta.x, g.delta.y) : run.base;
        deps.onState({ preview: layout === run.base ? null : layout, moving: false });
        return targetFor(key, layout, run.from, null, true);
      }
      if (key === 'out') return unchanged(key, false);
      const armed = key.endsWith(ARMED);
      const entry = run.entries.get(armed ? key.slice(0, -ARMED.length) : key);
      if (!entry) return unchanged(key, false);
      const caret = entry.tab?.kind === 'strip' ? entry.tab : null;
      if (JSON.stringify(tabDrag.target) !== JSON.stringify(caret)) tabDrag.target = caret;
      const label = entry.cand.label;
      const payload: unknown = run.carried
        ? ({ drop: entry.tab! } satisfies TabPayload)
        : entry.layout
          ? ({ layout: entry.layout, from: run.from } satisfies Payload)
          : ({ merge: entry.merge! } satisfies MergePayload);
      return {
        key,
        rects: armed && entry.armedRects ? entry.armedRects : idleRects(run, entry),
        landing: entry.landing,
        payload,
        ...(label ? { mark: { label: t(label), kind: entry.cand.target.kind === 'middle' ? 'tab' : entry.cand.target.kind } } : {}),
      };
    },

    commit(target, g) {
      const held = run;
      const payload = target.payload as Partial<Payload & TabPayload & MergePayload> | undefined;
      if (held?.torn) {
        finish();
        return;
      }
      if (held?.carried) {
        swallowNextClick();
        if (payload?.drop && commitTabDrop(held.carried, payload.drop)) held.wake?.();
        finish();
        return;
      }
      if (payload?.merge) {
        commitMerge(store, payload.merge.from, payload.merge.into, payload.merge.index);
      } else if (payload?.layout && payload.from) {
        if (payload.layout !== payload.from) store.commitLayout(payload.layout, payload.from);
      }
      if (g !== null) finish();
    },

    cancel() {
      if (run?.carried) swallowNextClick();
      finish();
    },

    stepFromTarget: true,
    step(id, step, prev) {
      const last = prev?.payload && typeof prev.payload === 'object' ? (prev.payload as Payload) : null;
      const from = last?.from ?? store.snapshot();
      const layout = last?.layout ?? from;
      const place = placeOf(layout, id as SlotId);
      const row = place ? layout.rows[place.rowAt] : undefined;
      if (!place || !row) return null;
      const geo = geometryOf(layout);
      const specs = dividerSpecs(layout, geo.tracks, deps.box(), gutter, true);
      const key = `k:${Date.now()}`;
      if (step.resize) {
        const sign = step.dir === 'right' || step.dir === 'down' ? 1 : -1;
        const horizontal = step.dir === 'left' || step.dir === 'right';
        let spec: DividerSpec | undefined;
        let flip = 1;
        if (horizontal) {
          spec = specs.find((one) => one.kind === 'col' && !one.mirror && one.rowId === row.id && one.seam?.index === place.slotAt);
          if (!spec) {
            spec = specs.find((one) => one.kind === 'col' && !one.mirror && one.rowId === row.id && one.seam?.index === place.slotAt - 1);
            flip = -1;
          }
        } else {
          const mine = (list: readonly SlotId[] | undefined): boolean => !!list?.includes(id as SlotId);
          spec = specs.find((one) => one.kind === 'row' && !one.mirror && mine(one.seg?.above));
          if (!spec) {
            spec = specs.find((one) => one.kind === 'row' && !one.mirror && mine(one.seg?.below));
            flip = -1;
          }
          if (!spec) {
            const lastAt = Math.min(place.rowAt + spanOf(row.slots[place.slotAt]!) - 1, layout.rows.length - 1);
            spec = specs.find((one) => one.kind === 'row' && one.rowId === layout.rows[lastAt]!.id);
            flip = 1;
            if (!spec && place.rowAt > 0) {
              spec = specs.find((one) => one.kind === 'row' && one.rowId === layout.rows[place.rowAt - 1]!.id);
              flip = -1;
            }
          }
        }
        if (!spec) return null;
        const px = sign * flip * KEY_PX;
        const next = applyDivider(layout, spec, horizontal ? px : 0, horizontal ? 0 : px);
        return next === layout ? null : targetFor(key, next, from, id as SlotId, true);
      }
      const order = visualOrder(row);
      const visual = order.findIndex((entry) => entry.kind === 'slot' && entry.slot.id === id);
      let target: DropTarget | null = null;
      if (step.dir === 'left') target = visual > 0 ? { kind: 'row', row: row.id, index: visual - 1 } : null;
      else if (step.dir === 'right') target = visual < order.length - 1 ? { kind: 'row', row: row.id, index: visual + 2 } : null;
      else {
        const other = layout.rows[place.rowAt + (step.dir === 'up' ? -1 : 1)];
        const mine = geo.rects.get(id as SlotId);
        if (other && mine) {
          const centre = mine.x + mine.w / 2;
          const index = (geo.tracks.rows[place.rowAt + (step.dir === 'up' ? -1 : 1)]?.cells ?? []).filter((c) => c.x + c.width / 2 < centre).length;
          target = { kind: 'row', row: other.id, index };
        }
      }
      if (!target) return null;
      const next = applyDrop(layout, id as SlotId, target, META);
      return next === layout ? null : targetFor(key, next, from, id as SlotId, false);
    },
  };
}
