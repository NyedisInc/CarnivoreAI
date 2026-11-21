<script lang="ts">
  import { flushSync, setContext, untrack, type Snippet } from 'svelte';
  import type { LayoutStore } from '../layout.svelte';
  import type { CellDragMerge } from '../pointer';
  import type { Layout, Slot, SlotId } from '../types';
  import { GUTTER } from '../tracks';
  import { registerBusy } from '../surface-busy';
  import { observeCell, sizeOf, surfaceKeyOf } from '../observe.svelte';
  import { viewport } from '../viewport.svelte';
  import { layoutZoom } from '../layout-zoom.svelte';
  import { raiseFlag } from '../../../lib/page-flags/page-flags';
  import { mountMotion, registerDropHost, type MotionHandle } from '../../../lib/motion-grid';
  import { primarySessionId } from '../../api/host';
  import { resolveDropKind } from '../../layout-editor/drop-kind';
  import { createRowsAdapter } from './rows-adapter';
  import { dividerSpecs } from './dividers';
  import { layoutGeometry } from './layout-rects';
  import { pendingFor, type Pending } from './pending';
  import DividerHandle from './DividerHandle.svelte';
  import DockCompass from './DockCompass.svelte';
  import type { CompassView } from '../dock-compass';

  let {
    gutter = GUTTER,
    renderCell,
    store,
    sizeKey: sizeKeyOverride,
    dropId,
    merge,
  }: {
    gutter?: number;
    sizeKey?: string;
    renderCell: Snippet<[Slot]>;
    store: LayoutStore;
    dropId?: string;
    merge?: (id: SlotId) => CellDragMerge | undefined;
  } = $props();

  setContext('oc:motion-surface', true);

  const rows = $derived(store.state.layout.rows);
  const sizeKey = $derived(sizeKeyOverride ?? surfaceKeyOf(store.page));
  const surface = $derived(sizeOf(sizeKey));
  const measured = $derived(store.page === 'home' || (surface.width > 0 && surface.height > 0));
  const zoomed = $derived(layoutZoom.zoomed);

  $effect(() => {
    if (store.page !== 'terminal') return;
    const held = layoutZoom.zoomed;
    if (held === null) return;
    if (rows.some((row) => row.slots.some((slot) => slot.id === held))) return;
    layoutZoom.forget(held);
  });

  const GHOST = '@ghost';
  const GHOST_W = 220;
  const GHOST_H = 32;

  let handle: MotionHandle | null = null;
  const elements = new Map<string, HTMLElement>();
  const bodies = new Map<string, HTMLElement>();
  let pending = $state<Pending | null>(null);
  let ui = $state<{ preview: Layout | null; moving: boolean }>({ preview: null, moving: false });
  let compass = $state.raw<CompassView | null>(null);
  let container: HTMLElement | null = null;

  const adapter = createRowsAdapter({
    store,
    box: () => {
      const box = sizeOf(untrack(() => sizeKey));
      return { width: box.width, height: box.height };
    },
    gutter,
    wide: () => viewport.wide,
    zoomed: () => layoutZoom.zoomed,
    container: () => container,
    merge: (id) => merge?.(id),
    onState: (state) => {
      ui = state;
    },
    onCompass: (view) => {
      compass = view;
    },
    onEnd: () => {
      pending = null;
    },
  });

  const slots = $derived.by(() => {
    const all = rows.flatMap((row) => row.slots);
    const extra = pending && !all.some((slot) => slot.id === pending!.id) ? [{ id: pending.id, fr: 1 } as Slot] : [];
    return [...all, ...extra];
  });

  const dividers = $derived.by(() => {
    if (!measured || zoomed) return [];
    const layout = ui.preview ?? store.state.layout;
    const geo = layoutGeometry(layout, surface.width, surface.height, gutter);
    return dividerSpecs(layout, geo.tracks, { width: surface.width, height: surface.height }, gutter, viewport.wide);
  });

  function wrapper(id: string) {
    return (el: HTMLElement) => {
      elements.set(id, el);
      handle?.register(id, el);
      handle?.sync(false);
      return () => {
        elements.delete(id);
        handle?.unregister(id);
      };
    };
  }

  function body(id: string) {
    return (el: HTMLElement) => {
      bodies.set(id, el);
      return () => {
        bodies.delete(id);
      };
    };
  }

  function render(id: string, size: { w: number; h: number }): void {
    const el = bodies.get(id);
    if (!el) return;
    el.style.width = `${size.w}px`;
    el.style.height = `${size.h}px`;
  }

  function mountSurface(node: HTMLElement) {
    container = node;
    const motion = mountMotion(node, adapter, {
      autoscroll: false,
      render,
      sizePaint: 'flip',
      lift: { tilt: false, maxW: 320, maxH: 200 },
    });
    handle = motion;
    const offBusy = registerBusy(() => motion.isBusy());
    for (const [id, el] of elements) motion.register(id, el);
    motion.sync(true);
    const offSettle = motion.on('settle', () => {
      pending = null;
    });
    const offHost = dropId
      ? registerDropHost(node, {
          id: dropId,
          takes: (kind) => pendingFor(store.state.layout, kind, primarySessionId(), store) !== null,
          accept(kind, ev) {
            const placed = pendingFor(store.state.layout, resolveDropKind(kind), primarySessionId(), store);
            if (!placed) return false;
            adapter.setPending(placed);
            const box = sizeOf(sizeKey);
            const found = layoutGeometry(placed.layout, box.width, box.height, gutter).rects.get(placed.id);
            let ok = false;
            if ((placed as Pending & { asMove?: boolean }).asMove) {
              ok = !!found && motion.beginExternal({ id: placed.id, rect: found, grab: { x: found.w / 2, y: 16 } }, ev, { as: 'move' });
            } else if (placed.ghost) {
              const ghost = elements.get(GHOST);
              if (ghost) {
                ghost.textContent = placed.ghost.label;
                const rect = { x: 0, y: 0, w: GHOST_W, h: GHOST_H };
                ok = motion.beginExternal({ id: GHOST, rect, grab: { x: GHOST_W / 2, y: GHOST_H / 2 } }, ev, { leaveOnDrop: true });
              }
            } else {
              flushSync(() => {
                pending = placed;
              });
              ok = !!found && motion.beginExternal({ id: placed.id, rect: found, grab: { x: found.w / 2, y: 16 } }, ev);
            }
            if (!ok) {
              adapter.setPending(null);
              pending = null;
            }
            return ok;
          },
          add(kind) {
            const placed = pendingFor(store.state.layout, resolveDropKind(kind), primarySessionId(), store);
            if (!placed || placed.tab) return false;
            store.commitLayout(placed.layout, store.snapshot());
            return true;
          },
        })
      : undefined;
    return () => {
      offHost?.();
      offBusy();
      offSettle();
      motion.destroy();
      handle = null;
      container = null;
    };
  }

  let sized = '';
  let sizedWidth = 0;
  $effect(() => {
    void store.state.layout;
    void zoomed;
    void measured;
    const key = `${surface.width}x${surface.height}`;
    untrack(() => {
      if (!handle) return;
      const resized = key !== sized;
      const caused = resized && handle.isBusy() && !!container?.style.height && surface.width === sizedWidth;
      sized = key;
      sizedWidth = surface.width;
      if (resized && !caused && handle.isBusy()) {
        handle.setEnabled(false);
        handle.setEnabled(true);
      }
      handle.sync(resized);
    });
  });

  function flagTerminalGrid(surfaceEl: HTMLElement): (() => void) | undefined {
    return surfaceEl.parentElement?.id === 'terminal-grid' ? raiseFlag('grid-surface') : undefined;
  }
</script>

<div
  class="oc-surface abs-surface"
  class:oc-surface-zoomable={store.page === 'terminal'}
  class:abs-moving={ui.moving}
  {@attach observeCell(sizeKey)}
  {@attach flagTerminalGrid}
  {@attach mountSurface}
>
  {#each measured ? slots : [] as slot (slot.id)}
    <div
      class="oc-cellslot abs-slot"
      class:abs-zoomed={zoomed === slot.id}
      data-slot={slot.id}
      data-abs-slot={slot.id}
      {@attach wrapper(slot.id)}
    >
      <div class="abs-body" {@attach body(slot.id)}>
        {@render renderCell(slot)}
      </div>
    </div>
  {/each}
  {#each dividers as spec (spec.id)}
    <DividerHandle {spec} {store} />
  {/each}
  <div class="abs-ghost" aria-hidden="true" {@attach wrapper(GHOST)}></div>
  <DockCompass view={compass} />
</div>
