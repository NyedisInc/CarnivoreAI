import { homeBoards } from '../engine/home-sync.svelte';
import { openDashboardPopout, openHomePopout, openWallboard } from '../../popout/popout';
import { openTabPopout } from '../../lib/dynamic-tabs/tab-popout';
import { cplugPopoutTabsOn } from '../../cplugs/host/readers';
import { t } from '../../lib/i18n/index.svelte';

export type OpenTargetKind = 'home' | 'wallboard' | 'dashboard' | 'tab';

export interface OpenTarget {
  id: string;
  kind: OpenTargetKind;
  label: string;
  board: string | null;
  open: () => void;
}

export function popOutHome(win: Window = window): Window | null {
  return homeBoards.ready ? openDashboardPopout(homeBoards.active, win) : openHomePopout(win);
}

export function otherDashboards(): { id: string; name: string }[] {
  return homeBoards.ready ? homeBoards.list.filter((board) => board.id !== homeBoards.active) : [];
}

export function openTargets(): OpenTarget[] {
  const active = homeBoards.ready ? (homeBoards.list.find((board) => board.id === homeBoards.active) ?? null) : null;
  return [
    {
      id: 'home',
      kind: 'home',
      label: active ? t('opscenter.open.home_named', { name: active.name }) : t('opscenter.open.home'),
      board: active?.id ?? null,
      open: () => void popOutHome(),
    },
    { id: 'wallboard', kind: 'wallboard', label: t('opscenter.open.wallboard'), board: null, open: () => void openWallboard() },
    ...otherDashboards().map((board) => ({
      id: `dashboard:${board.id}`,
      kind: 'dashboard' as const,
      label: board.name,
      board: board.id,
      open: () => void openDashboardPopout(board.id),
    })),
    ...cplugPopoutTabsOn().map((def) => ({
      id: `tab:${def.id}`,
      kind: 'tab' as const,
      label: t(def.labelKey, { count: 0 }),
      board: null,
      open: () => void openTabPopout(def.id, window, def.popoutParams?.(), def.popoutMulti === true),
    })),
  ];
}

export function menuRowPopout(id: string): (() => void) | null {
  const tab = openTargets().find((one) => one.kind === 'tab' && one.id === `tab:${id}`);
  return tab ? tab.open : null;
}
