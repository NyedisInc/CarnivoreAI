<script lang="ts">
  /* something else */
  import { drawerSurface } from '../../lib/drawer-tabs/drawer-surface.svelte';
  import { viewport } from '../engine/viewport.svelte';
  import type { SlotId } from '../engine/types';
  import { gestureActive } from '../engine/pointer';
  import { checkLayoutEditor, editingStore, finishLayoutEditor, layoutEditor } from './editor.svelte';
  import EditOverlay from './EditOverlay.svelte';

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
    if (!layoutEditor.active || event.key !== 'Escape' || event.defaultPrevented) return;
    if (gestureActive()) return;
    const target = event.target as Element | null;
    if (target?.closest?.('[role="menu"], [role="dialog"], [role="alertdialog"]')) return;
    event.preventDefault();
    finishLayoutEditor();
  }

  function onFocusCell(event: Event): void {
    if (!layoutEditor.active) return;
    const slot = (event.target as Element | null)?.closest?.('.oc-cellslot[data-slot]');
    if (slot) layoutEditor.focusSlot = slot.getAttribute('data-slot') as SlotId;
  }

  const store = $derived(layoutEditor.active ? editingStore() : null);
</script>

<svelte:window onkeydown={onKey} onpointerdowncapture={onFocusCell} onfocusincapture={onFocusCell} />

{#if layoutEditor.active && store && layoutEditor.page}
  <EditOverlay />
{/if}
