import { sidebarWidgets, type SidebarWidgetRegistry } from './registry';
import { menuShowing } from './escape-guards';
import { barPinned } from '../widget-bars/bar-pin-action';
import { widgetPresent } from './rail-model';
import { SESSION_LIST_WIDGET } from './widget-ids';
import { isTabBodyPart, type SidebarWidget } from './types';

const state = $state<{ active: string | null }>({ active: null });

export function activeFlyout(): string | null {
  return state.active;
}

export function flyoutWidget(id: string | null, registry: SidebarWidgetRegistry = sidebarWidgets): SidebarWidget | null {
  const widget = id ? registry.get(id) : undefined;
  return widget && widget.surface === 'flyout' ? widget : null;
}

export function openFlyout(id: string, registry: SidebarWidgetRegistry = sidebarWidgets): boolean {
  const widget = flyoutWidget(id, registry);
  // cannot be opened
  if (!widget || !widgetPresent(widget)) return false;
  if (widget.action) {
    widget.action();
    return false;
  }
  state.active = id;
  return true;
}

export function closeFlyout(): boolean {
  if (state.active === null) return false;
  state.active = null;
  return true;
}

export function showFlyout(id: string, registry: SidebarWidgetRegistry = sidebarWidgets): string | null {
  if (id === SESSION_LIST_WIDGET) closeFlyout();
  else openFlyout(id, registry);
  return state.active;
}

export function closeFlyoutIfGone(registry: SidebarWidgetRegistry = sidebarWidgets): boolean {
  const open = state.active;
  if (open === null) return false;
  const widget = flyoutWidget(open, registry);
  return widget !== null && widgetPresent(widget) ? false : closeFlyout();
}

export function pressRail(id: string, registry: SidebarWidgetRegistry = sidebarWidgets): string | null {
  if (id === SESSION_LIST_WIDGET || id === state.active) closeFlyout();
  else openFlyout(id, registry);
  return state.active;
}

export function dismissTransientFlyout(registry: SidebarWidgetRegistry = sidebarWidgets): boolean {
  return flyoutWidget(state.active, registry)?.dismissOnOutsideClick === true ? closeFlyout() : false;
}

export function hostedTab(widget: SidebarWidget): string | null {
  const body = widget.parts.body;
  return body && isTabBodyPart(body) ? body.tab : null;
}

export function flyoutShowsTab(tab: string, registry: SidebarWidgetRegistry = sidebarWidgets): boolean {
  const widget = flyoutWidget(state.active, registry);
  return widget !== null && hostedTab(widget) === tab;
}

function innerPopupOpen(doc: Document, host: Element | null): boolean {
  if ([...doc.querySelectorAll('[role="menu"]')].some(menuShowing)) return true;
  return host !== null && host.querySelector('[aria-haspopup][aria-expanded="true"]') !== null;
}

/* Escape is never claimed with no slide-out open */
export function handleFlyoutEscape(event: KeyboardEvent, host: Element | null, doc: Document = document): boolean {
  if (event.key !== 'Escape' || event.defaultPrevented || state.active === null) return false;
  if (barPinned('rail')) return false;
  if (innerPopupOpen(doc, host)) return false;
  const was = state.active;
  closeFlyout();
  event.preventDefault();
  event.stopPropagation();
  doc.querySelector<HTMLElement>(`[data-rail-widget="${was}"]`)?.focus();
  return true;
}

export function handleOutsidePress(
  event: Event,
  inside: readonly (Element | null)[],
  registry: SidebarWidgetRegistry = sidebarWidgets,
): boolean {
  const widget = flyoutWidget(state.active, registry);
  if (!widget?.dismissOnOutsideClick) return false;
  const target = event.target as Node | null;
  if (!target) return false;
  if (inside.some((el) => el?.contains(target))) return false;
  if ((target as Element).closest?.('[role="menu"]')) return false;
  return closeFlyout();
}

export function railHostsTab(tab: string, registry: SidebarWidgetRegistry = sidebarWidgets): boolean {
  return registry.all().some((widget) => widget.surface === 'flyout' && hostedTab(widget) === tab);
}
