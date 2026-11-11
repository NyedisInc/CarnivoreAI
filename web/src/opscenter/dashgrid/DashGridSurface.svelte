<script lang="ts">
  import { onMount, setContext, untrack } from 'svelte';
  import CellHost from '../CellHost.svelte';
  import type { LayoutStore } from '../engine/layout.svelte';
  import { META, isInstanceId, metaFor } from '../engine/meta';
  import type { SlotId } from '../engine/types';
  import { mountMotion, registerDropHost, type MotionHandle, type Rect } from '../../lib/motion-grid';
  import { t } from '../../lib/i18n/index.svelte';
  import { layoutEditor, addForDrop } from '../layout-editor/editor.svelte';
  import { createDashAdapter, colsFor } from './dash-adapter';
  import { commitDashLayout, dashItems, setDashBusy } from './dash-store.svelte';
  import { createEnableGate } from './edit-gate';

  let { store, readOnly = false }: { store: LayoutStore; readOnly?: boolean } = $props();

  setContext('oc:motion-surface', true);

  let host = $state<HTMLElement | null>(null);
  let width = $state(0);
  let handle: MotionHandle | null = null;
  const wrappers = new Map<string, HTMLElement>();
  const bodies = new Map<string, HTMLElement>();
  let syncQueued = false;

  const cols = $derived(colsFor(width));
  const items = $derived(width > 0 ? dashItems(store.state.layout, cols) : []);
  const editing = $derived(!readOnly && layoutEditor.active && layoutEditor.page === 'home');

  function titleOf(id: SlotId): string {
    const meta = metaFor(id, META);
    return meta.titleName ?? t(meta.titleKey);
  }

  function queueSync(instant: boolean): void {
    if (syncQueued) return;
    syncQueued = true;
    queueMicrotask(() => {
      syncQueued = false;
      handle?.sync(instant);
    });
  }

  function dropPending(id: string): void {
    if (isInstanceId(id as SlotId)) store.remove(id as SlotId);
    else store.hide(id as SlotId);
  }

  function wrapper(id: string) {
    return (el: HTMLElement) => {
      wrappers.set(id, el);
      handle?.register(id, el);
      queueSync(true);
      return () => {
        wrappers.delete(id);
        bodies.delete(id);
        handle?.unregister(id);
      };
    };
  }

  function body(id: string) {
    return (el: HTMLElement) => {
      bodies.set(id, el);
    };
  }

  function render(id: string, size: { w: number; h: number }): void {
    const el = bodies.get(id);
    if (!el) return;
    el.style.width = `${size.w}px`;
    el.style.height = `${size.h}px`;
  }

  function pendingRect(id: string, ev: PointerEvent): { rect: Rect; grab: { x: number; y: number } } | null {
    const base = handle && host ? host.getBoundingClientRect() : null;
    const r = items.find((i) => i.id === id);
    const at = wrappers.get(id);
    if (!base || !r || !at) return null;
    const w = parseFloat(at.style.width) || 320;
    const h = parseFloat(at.style.height) || 200;
    const grab = { x: Math.min(w / 2, 48), y: Math.min(h / 2, 16) };
    return { rect: { x: ev.clientX - base.left - grab.x, y: ev.clientY - base.top - grab.y, w, h }, grab };
  }

  onMount(() => {
    if (!host) return;
    const el = host;
    const ro = new ResizeObserver((entries) => {
      const next = Math.round(entries[0]?.contentRect.width ?? 0);
      if (next <= 0 || next === width) return;
      width = next;
      queueSync(true);
    });
    ro.observe(el);
    width = Math.round(el.getBoundingClientRect().width);
    const adapter = createDashAdapter({
      cols: () => cols,
      width: () => width,
      items: () => items,
      commit: (next) => commitDashLayout(store.state.layout, cols, next),
      cancelExternal: dropPending,
      label: (id) => titleOf(id as SlotId),
    });
    handle = mountMotion(el, adapter, { enabled: false, render, scroller: el.closest<HTMLElement>('.oc-content') });
    for (const [id, w] of wrappers) handle.register(id, w);
    handle.sync(true);
    setDashBusy(() => handle?.isBusy() ?? false);
    const gate = createEnableGate(handle);
    const stopGate = $effect.root(() => {
      $effect(() => gate(editing));
      $effect(() => {
        void items;
        void cols;
        untrack(() => queueSync(false));
      });
    });
    const unhost = registerDropHost(el, {
      id: 'dashboard',
      takes: () => editing,
      accept(kind, ev) {
        if (!editing) return false;
        const id = addForDrop(kind);
        if (!id) return false;
        void Promise.resolve().then(() => {
          const spot = pendingRect(id, ev);
          if (!spot || !handle?.beginExternal({ id, rect: spot.rect, grab: spot.grab }, ev)) dropPending(id);
        });
        return true;
      },
      add: (kind) => editing && addForDrop(kind) !== null,
    });
    return () => {
      unhost();
      stopGate();
      setDashBusy(null);
      handle?.destroy();
      handle = null;
      ro.disconnect();
    };
  });
</script>

<div class="oc-dash" class:oc-dash-edit={editing} style:--oc-dash-cols={cols} bind:this={host} data-dash-surface>
  {#if editing}<div class="oc-dash-guides" aria-hidden="true"></div>{/if}
  {#each items as item (item.id)}
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <div
      class="oc-dash-item"
      data-dash-id={item.id}
      data-slot={item.id}
      role="group"
      aria-label={titleOf(item.id)}
      tabindex={editing ? 0 : undefined}
      {@attach wrapper(item.id)}
    >
      <div class="oc-dash-body" {@attach body(item.id)}>
        <CellHost id={item.id} {store} />
      </div>
      {#if editing}
        {#each ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as edge (edge)}
          <i class={`motion-handle motion-handle--${edge}`} data-dash-resize={edge} aria-hidden="true"></i>
        {/each}
      {/if}
    </div>
  {/each}
</div>
