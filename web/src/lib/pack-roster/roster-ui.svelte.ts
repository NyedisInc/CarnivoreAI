import type { FilterKey, SortKey } from './roster-model';

export type PaneTab = 'overview' | 'projects' | 'link' | 'ssh';
export type RosterMode = 'add' | null;

export const rosterUi = $state<{
  filter: FilterKey;
  sort: SortKey;
  view: 'cards' | 'list';
  q: string;
  openId: string | null;
  tab: PaneTab;
  mode: RosterMode;
  route: 'code' | 'ssh' | 'host' | 'older';
  settings: boolean | null;
  landSsh: boolean;
  fold: Record<string, boolean>;
  prefillLogin: string | null;
}>({ filter: 'all', sort: 'status', view: 'cards', q: '', openId: null, tab: 'overview', mode: null, route: 'code', settings: null, landSsh: false, fold: {}, prefillLogin: null });

export function openAdd(route: 'code' | 'ssh' | 'host' | 'older' = rosterUi.route): void {
  rosterUi.route = route;
  rosterUi.mode = 'add';
  rosterUi.openId = null;
}

export function openComputer(id: string, tab?: PaneTab): void {
  rosterUi.mode = null;
  rosterUi.openId = id;
  if (tab) rosterUi.tab = tab;
}

/* the reading pane */
export function closePane(): void {
  rosterUi.mode = null;
  rosterUi.openId = null;
}

export function setSettings(open: boolean): void {
  rosterUi.settings = open;
}
