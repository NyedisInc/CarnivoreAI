import { terminalLayout } from './layout.svelte';

let zoomed = $state<string | null>(null);

function componentCount(): number {
  let count = 0;
  for (const row of terminalLayout.state.layout.rows) count += row.slots.length;
  return count;
}

export const layoutZoom = {
  get zoomed(): string | null {
    return zoomed;
  },

  isZoomed(id: string): boolean {
    return zoomed === id;
  },

  isCovered(groupSlot: string | null): boolean {
    return groupSlot !== null && zoomed !== null && zoomed !== groupSlot;
  },

  get canZoom(): boolean {
    return componentCount() > 1;
  },

  toggle(id: string): void {
    if (!this.canZoom) return;
    zoomed = zoomed === id ? null : id;
  },

  restore(): void {
    zoomed = null;
  },

  forget(id: string): void {
    if (zoomed === id) zoomed = null;
  },
};

export const ZOOM_KEY_ROWS: readonly { keys: string; labelKey: string }[] = [
  { keys: 'shift cmd enter', labelKey: 'keys.page.zoom.toggle' },
  { keys: 'shift esc', labelKey: 'keys.page.zoom.restore' },
];

function focusedSlot(): string | null {
  const active = document.activeElement;
  const id = active instanceof Element ? active.closest<HTMLElement>('[data-slot]')?.dataset.slot : undefined;
  if (!id) return null;
  for (const row of terminalLayout.state.layout.rows) {
    if (row.slots.some((slot) => slot.id === id)) return id;
  }
  return null;
}

export function watchZoomKeys(): () => void {
  const onKeyDown = (event: KeyboardEvent): void => {
    if (event.key === 'Enter' && event.shiftKey && event.metaKey && !event.ctrlKey && !event.altKey) {
      const slot = focusedSlot();
      if (slot === null || !layoutZoom.canZoom) return;
      event.preventDefault();
      event.stopPropagation();
      layoutZoom.toggle(slot);
      return;
    }
    if (event.key !== 'Escape' || !event.shiftKey) return;
    if (layoutZoom.zoomed === null) return;
    event.preventDefault();
    event.stopPropagation();
    layoutZoom.restore();
  };
  window.addEventListener('keydown', onKeyDown, true);
  return () => window.removeEventListener('keydown', onKeyDown, true);
}
