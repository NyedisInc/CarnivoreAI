import { SvelteMap } from 'svelte/reactivity';
import { isTabBodyPart, type SidebarRegistration, type SidebarWidget } from './types';

export function checkSidebarWidget(widget: SidebarWidget): SidebarRegistration {
  if (Object.keys(widget.parts).length === 0) return { ok: false, reason: 'no-parts' };
  if (widget.surface === 'flyout' && !widget.tint) return { ok: false, reason: 'tint-required' };
  if (widget.surface !== 'flyout' && widget.tint) return { ok: false, reason: 'tint-not-allowed' };
  if (widget.surface !== 'flyout' && widget.dismissOnOutsideClick) return { ok: false, reason: 'outside-click-not-allowed' };
  if (widget.surface !== 'flyout' && Object.values(widget.parts).some(isTabBodyPart)) return { ok: false, reason: 'tab-body-not-allowed' };
  return { ok: true };
}

export class SidebarWidgetRegistry {
  #widgets = new SvelteMap<string, SidebarWidget>();

  register(widget: SidebarWidget): SidebarRegistration {
    const check: SidebarRegistration = this.#widgets.has(widget.id) ? { ok: false, reason: 'duplicate-id' } : checkSidebarWidget(widget);
    if (!check.ok) {
      console.warn('sidebar widgets: refused to register', { id: widget.id, reason: check.reason });
      return check;
    }
    this.#widgets.set(widget.id, widget);
    return check;
  }

  get(id: string): SidebarWidget | undefined {
    return this.#widgets.get(id);
  }

  has(id: string): boolean {
    return this.#widgets.has(id);
  }

  all(): SidebarWidget[] {
    return [...this.#widgets.values()].sort((a, b) => a.order - b.order);
  }
}

export const sidebarWidgets = new SidebarWidgetRegistry();
