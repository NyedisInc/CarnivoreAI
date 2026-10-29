import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import { openDashboardPopout } from '../../popout/popout';
import { popOutHome } from '../../opscenter/shell/open-targets';
import { openDashboardsScreen } from '../dashboards/screen-host';
import { showDashboard } from '../dashboards/dashboard-actions.svelte';
import { closeDrawerAfterSwitch } from './menu-hotkeys';

export interface MenuDashboardRow {
  id: string;
  name: string;
  home: boolean;
  viewing: boolean;
}

export function menuDashboardRows(): MenuDashboardRow[] {
  if (!homeBoards.ready) return [];
  return homeBoards.list
    .map((board) => ({ id: board.id, name: board.name, home: board.id === homeBoards.active, viewing: board.id === homeBoards.viewing }))
    .sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }) || a.id.localeCompare(b.id));
}

export const menuDashboardsFold = $state({ open: false });

export function toggleMenuDashboards(): void {
  menuDashboardsFold.open = !menuDashboardsFold.open;
  menuPreview.id = null;
}

export function editMenuDashboards(): void {
  menuPreview.id = null;
  void openDashboardsScreen();
  closeDrawerAfterSwitch();
}

export const menuPreview = $state<{ id: string | null; anchor: HTMLElement | null }>({ id: null, anchor: null });

export function showMenuPreview(id: string, anchor: HTMLElement | null): void {
  menuPreview.id = id;
  menuPreview.anchor = anchor;
}

export function hideMenuPreview(id: string): void {
  if (menuPreview.id === id) menuPreview.id = null;
}

export function openMenuDashboard(id: string): void {
  menuPreview.id = null;
  showDashboard(id);
  closeDrawerAfterSwitch();
}

export function popOutMenuDashboard(id: string): void {
  menuPreview.id = null;
  if (id === homeBoards.active) popOutHome();
  else openDashboardPopout(id);
}
