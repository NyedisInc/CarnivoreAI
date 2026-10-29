import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
import { t } from '../../lib/i18n/index.svelte';
import { sidebarTabs } from '../../lib/dynamic-tabs/tab-store.svelte';
import { widgetArea } from '../../lib/dynamic-tabs/widget-area.svelte';
import type { RailEdge } from '../../lib/session-rail/rail-model';
import { widgetBars } from '../../lib/widget-bars/bar-settings.svelte';
import { areaMenuNodes, barMenuNodes } from '../../lib/widget-menu/bar-menu';
import { barPinned, stripPinsOffered, toggleBarPin } from '../../lib/widget-bars/bar-pin-action';
import { editablePage, layoutEditor, toggleLayoutEditor } from './editor.svelte';
import { isMenuKey } from '../../lib/zone-shell/key-nav';

export type MenuSurface = 'home' | 'terminal' | 'warroom';

export type EmptyTarget = 'empty' | RailEdge | 'area';

export const emptyMenu: { at: { x: number; y: number } | null; surface: MenuSurface; target: EmptyTarget } = $state({ at: null, surface: 'home', target: 'empty' });

export function surfaceOf(target: EventTarget | null): MenuSurface {
  if (target instanceof Element && target.closest('#warroom-screen') !== null) return 'warroom';
  if (document.querySelector('#warroom-screen .oc-surface') !== null) return 'warroom';
  if (target instanceof Element && target.closest('#terminal-screen') !== null) return 'terminal';
  if (document.querySelector('#launchpad-screen.active') !== null) return 'home';
  return document.querySelector('#terminal-screen.active') !== null ? 'terminal' : 'home';
}

const WIDGET = '.oc-cellslot:not(.oc-cellslot-reserved)';

export function onWidget(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(WIDGET) !== null;
}

const RAIL_BUSY = '.rail__key, [data-rail-slideout]';

export function onRailEmptySpace(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(RAIL_BUSY) === null;
}

export function canOpen(): boolean {
  return layoutEditor.active || editablePage() !== null;
}

function closeEmptyMenu(): void {
  emptyMenu.at = null;
}

export function emptyMenuNodes(): MenuNode[] {
  const target = emptyMenu.target;
  const toggleEdit = canOpen() ? () => void toggleLayoutEditor() : null;
  if (target === 'side' || target === 'bottom') {
    const bar = widgetBars.view[target];
    return barMenuNodes({
      size: bar.size,
      pinned: barPinned(target),
      editing: layoutEditor.active,
      setSize: (size) => void widgetBars.set(target, { size }),
      togglePin: stripPinsOffered() ? () => void toggleBarPin(target) : null,
      toggleEdit,
      onClose: closeEmptyMenu,
    });
  }
  if (target === 'area') {
    const tab = sidebarTabs.active();
    return areaMenuNodes({ state: widgetArea.stateFor(tab), editing: layoutEditor.active, setState: (state) => widgetArea.set(tab, state), toggleEdit, onClose: closeEmptyMenu });
  }
  return [
    {
      id: 'toggle-edit-layout',
      label: layoutEditor.active ? t('opscenter.empty_menu.done') : t('opscenter.empty_menu.edit'),
      run: () => {
        closeEmptyMenu();
        toggleLayoutEditor();
      },
    },
  ];
}

export function onContextMenu(event: MouseEvent): void {
  if (event.defaultPrevented || onWidget(event.target) || !canOpen()) return;
  event.preventDefault();
  emptyMenu.surface = surfaceOf(event.target);
  emptyMenu.target = 'empty';
  emptyMenu.at = { x: event.clientX, y: event.clientY };
}

export function onMenuKey(event: KeyboardEvent, surface: HTMLElement): void {
  if (!isMenuKey(event) || event.target !== surface || !canOpen()) return;
  event.preventDefault();
  const box = surface.getBoundingClientRect();
  emptyMenu.surface = surfaceOf(surface);
  emptyMenu.target = 'empty';
  emptyMenu.at = { x: box.left + 16, y: box.top + 16 };
}

const ZONE_BUSY = '[data-zone-item], .dz-gplace, .dz-gwrap, button, a, input, select';

function openOnEmpty(event: MouseEvent, empty: boolean, target: EmptyTarget): void {
  if (event.defaultPrevented || !empty) return;
  if (target === 'empty' && !canOpen()) return;
  event.preventDefault();
  emptyMenu.surface = surfaceOf(event.target);
  emptyMenu.target = target;
  emptyMenu.at = { x: event.clientX, y: event.clientY };
}

export function onRailContextMenu(event: MouseEvent, edge: RailEdge): void {
  openOnEmpty(event, onRailEmptySpace(event.target), edge);
}

const BAR_OWN_FOCUS = '[data-bar-handle], [data-bar-edge]';

export function onRailMenuKey(event: KeyboardEvent, edge: RailEdge): void {
  if (!isMenuKey(event) || event.defaultPrevented) return;
  const own = event.target instanceof Element ? event.target.closest<HTMLElement>(BAR_OWN_FOCUS) : null;
  if (!own) return;
  event.preventDefault();
  event.stopPropagation();
  const box = own.getBoundingClientRect();
  emptyMenu.surface = surfaceOf(own);
  emptyMenu.target = edge;
  emptyMenu.at = { x: box.left, y: box.top };
}

export function onZoneContextMenu(event: MouseEvent): void {
  openOnEmpty(event, event.target instanceof Element && event.target.closest(ZONE_BUSY) === null, 'area');
}
