<script lang="ts">
  import { drawerSurface } from '../../lib/drawer-tabs/drawer-surface.svelte';
  import { viewport } from '../engine/viewport.svelte';
  import type { SlotId } from '../engine/types';
  import { gestureActive } from '../engine/pointer';
  import { storeFor } from '../../lib/drawer-tabs/drawer-surface.svelte';
  import { homeLayout } from '../engine/layout.svelte';
  import { checkLayoutEditor, closeWidgetDrawer, editingStore, finishLayoutEditor, layoutEditor, openWidgetDrawer, surfaceDrawer } from './editor.svelte';
  import EditOverlay from './EditOverlay.svelte';
  import WidgetDrawer from './WidgetDrawer.svelte';

  $effect(() => {
    const open = (event: Event): void => {
      const surface = (event as CustomEvent<{ surface?: string }>).detail?.surface;
      if (surface) openWidgetDrawer(surface);
    };
    document.addEventListener('oc-widget-drawer-open', open);
    return () => document.removeEventListener('oc-widget-drawer-open', open);
  });

  const drawerPage = $derived(surfaceDrawer.surface === 'terminal' ? 'terminal' : surfaceDrawer.surface === 'warroom' ? 'warroom' : 'home');
  const drawerStore = $derived(storeFor(drawerPage) ?? homeLayout);

  const SESSION_CHECK_MS = 500;

  $effect(() => {
    void drawerSurface.page;
    void viewport.wide;
    checkLayoutEditor();
    const bar = (globalThis as { SessionSidebarBar?: { paint?: () => void } }).SessionSidebarBar;
    bar?.paint?.();
  });

  $effect(() => {
    if (!layoutEditor.active) return;
    const timer = setInterval(checkLayoutEditor, SESSION_CHECK_MS);
    return () => clearInterval(timer);
  });

  function onKey(event: KeyboardEvent): void {
    if (surfaceDrawer.surface && event.key === 'Escape' && !event.defaultPrevented) {
      closeWidgetDrawer();
      return;
    }
    if (!layoutEditor.active || event.key !== 'Escape' || event.defaultPrevented) return;
    if (gestureActive()) return;
    const target = event.target as Element | null;
    if (target?.closest?.('[role="menu"], [role="dialog"], [role="alertdialog"]')) return;
    event.preventDefault();
    finishLayoutEditor();
  }

  function onFocusCell(event: Event): void {
    if (!layoutEditor.active) return;
    const slot = (event.target as Element | null)?.closest?.('.oc-cellslot[data-slot], .oc-dash-item[data-slot]');
    if (slot) layoutEditor.focusSlot = slot.getAttribute('data-slot') as SlotId;
  }

  const store = $derived(layoutEditor.active ? editingStore() : null);
</script>

<svelte:window onkeydown={onKey} onpointerdowncapture={onFocusCell} onfocusincapture={onFocusCell} />

{#if layoutEditor.active && store && layoutEditor.page}
  <EditOverlay />
{/if}

{#if surfaceDrawer.surface && !layoutEditor.active}
  <WidgetDrawer store={drawerStore} page={drawerPage} surface={surfaceDrawer.surface} />
{/if}
