import {
  openBlueprints,
  openHome,
  openHosts,
  openLedger,
  openWidgets,
  openWrappers,
  openSettings,
} from '../api';
import { railHint } from './rail-hints';
import { viewBoard } from '../engine/home-sync.svelte';
import { META } from '../engine/meta';
import { openSessionsScreen } from '../../lib/sessions-page/screen-host';
import { openChangelogScreen, openDocsScreen } from '../../lib/info-pages/screen-host';
import { openWarezScreen } from '../../lib/catalog/warez-host';
import { openAutomationsScreen } from '../../lib/automations/screen-host';
import { openWarroomScreen } from '../../lib/warroom/screen-host';
import { warroomAvailable } from '../../lib/warroom/phone.svelte';
import { cplugMenuLinks } from '../../cplugs/host/readers';

export interface RailItem {
  id: string;
  icon: string;
  labelKey: string;
  hint: string;
  run?: () => void;
  visible?: () => boolean;
  badge?: () => number | null;
  pressed?: () => boolean;
  widgetId?: string;
  close?: () => void;
}

export function railItemVisible(item: RailItem): boolean {
  return item.visible ? item.visible() : true;
}

function showDefaultDashboard(): void {
  void viewBoard(null);
  void openHome();
}

export const RAIL_RUN: Record<string, () => void> = {
  home: showDefaultDashboard,
  dashboards: showDefaultDashboard,
  sessions: () => void openSessionsScreen(),
  warroom: () => void openWarroomScreen(),
  widgets: () => void openWidgets(),
  warez: () => void openWarezScreen(),
  blueprints: () => void openBlueprints(),
  automations: () => void openAutomationsScreen(),
  providers: () => void openLedger(),
  settings: () => void openSettings(),
  wrappers: () => void openWrappers(),
  hosts: () => void openHosts(),
  docs: () => void openDocsScreen(),
  changelog: () => void openChangelogScreen(),
};

function row(id: string, icon: string, labelKey: string, visible?: () => boolean): RailItem {
  return { id, icon, labelKey, hint: railHint(id), run: RAIL_RUN[id], ...(visible ? { visible } : {}) };
}

export const WARROOM_ROW: RailItem = row('warroom', META.warroom.icon, 'opscenter.nav.warroom', warroomAvailable);

export const RAIL_DESTINATIONS: RailItem[] = [
  row('dashboards', 'layout', 'opscenter.nav.dashboards'),
  row('sessions', 'folder', 'opscenter.nav.sessions'),
  row('automations', 'clock', 'opscenter.nav.automations'),
  row('warez', 'floppy-525', 'opscenter.nav.warez'),
  row('widgets', 'grid', 'opscenter.nav.widgets'),
  row('blueprints', 'cube', 'blueprint.title'),
  row('providers', 'activity', 'opscenter.nav.providers'),
  row('hosts', 'wolf', 'opscenter.nav.hosts'),
  row('settings', 'gear', 'opscenter.nav.settings'),
  ...cplugMenuLinks(),
];

export const RAIL_HELP_LINKS: RailItem[] = [
  row('docs', 'docs', 'opscenter.nav.documentation'),
  row('changelog', 'changelog', 'opscenter.nav.changelog'),
];
